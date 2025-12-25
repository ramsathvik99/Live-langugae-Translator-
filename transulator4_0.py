'''
import socket
import threading
import speech_recognition as sr
from deep_translator import GoogleTranslator
import queue
import time
import uuid
from gtts import gTTS
import pygame
import os
import streamlit as st

# ---------------- Global Variables ----------------
PORT = 5001
recognizer = sr.Recognizer()
tts_queue = queue.Queue()
translator_instance = GoogleTranslator(source='auto', target='en')
LANGS = translator_instance.get_supported_languages(as_dict=True)
LANGS = {code: name.capitalize() for name, code in LANGS.items()}

stop_event = threading.Event()   # for stopping threads
active_threads = []
speaking_event = threading.Event()

# Init pygame mixer for non-blocking playback
pygame.mixer.init()

# Store the current TTS language globally
current_tts_lang = ["en"]

def clear_tts_queue():
    while not tts_queue.empty():
        try:
            tts_queue.get_nowait()
        except queue.Empty:
            break

# ---------------- TTS Worker ----------------
def tts_worker():
    while not stop_event.is_set():
        try:
            text = tts_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            filename = f"{uuid.uuid4()}.mp3"
            tts = gTTS(text=text, lang=current_tts_lang[0])
            tts.save(filename)

            speaking_event.set()  # 🔇 Block mic while speaking
            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.1)

            pygame.mixer.music.stop()
            speaking_event.clear()   # 🎤 Allow mic again
            os.remove(filename)
        except Exception as e:
            st.error(f"⚠️ TTS error: {e}")
            speaking_event.clear()

# ---------------- Networking ----------------
def connect_auto(partner_ip, port):
    while not stop_event.is_set():
        if partner_ip:
            try:
                st.write(f"🔗 Trying client → {partner_ip}:{port} …")
                c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                c.settimeout(5)
                c.connect((partner_ip, port))
                c.settimeout(None)
                st.success("✅ Connected as client")
                return c
            except Exception as e:
                if stop_event.is_set():
                    break
                st.warning(f"❌ Client connect failed: {e}")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.settimeout(7)
            s.bind(("0.0.0.0", port))
            s.listen(1)
            st.info("📡 Listening as server for 7s…")
            conn, addr = s.accept()
            st.success(f"🤝 Partner connected from {addr}")
            s.close()
            return conn
        except Exception as e:
            if stop_event.is_set():
                break
            st.warning(f"⏱ No incoming connection yet: {e}")
        finally:
            try:
                s.close()
            except:
                pass
        time.sleep(2)

# ---------------- Audio Pipelines ----------------
def listen_and_send(sock, my_lang):
    while not stop_event.is_set():
        try:
            st.info("🎤 Listening... speak now.")
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
                if stop_event.is_set():
                    break
                audio = recognizer.listen(source, phrase_time_limit=6, timeout=3)

            if stop_event.is_set():
                break

            text = recognizer.recognize_google(audio, language=my_lang)
            st.write(f"🗣 You said ({LANGS[my_lang]}): {text}")
            packet = f"{my_lang}:{text}\n"
            sock.sendall(packet.encode("utf-8"))
            time.sleep(0.1)
        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            st.warning("🤔 Didn’t catch that.")
        except Exception as e:
            if not stop_event.is_set():
                st.error(f"⚠️ Mic/Send error: {e}")
            time.sleep(1)

def receive_translate_speak(sock, my_lang):
    buffer = b""
    while not stop_event.is_set():
        try:
            chunk = sock.recv(4096)
            if not chunk:
                st.warning("🔌 Connection closed.")
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                msg = line.decode("utf-8", errors="replace").strip()
                if not msg or ":" not in msg:
                    continue
                src_lang, text = msg.split(":", 1)
                st.write(f"📥 Received ({LANGS.get(src_lang, src_lang)}): {text}")
                try:
                    translated = GoogleTranslator(source=src_lang, target=my_lang).translate(text)
                except Exception as e:
                    st.error(f"⚠️ Translation error: {e}")
                    translated = text
                st.success(f"🔊 Speaking ({LANGS[my_lang]}): {translated}")
                clear_tts_queue()
                tts_queue.put(translated)
        except Exception as e:
            if stop_event.is_set():
                break
            st.error(f"⚠️ Receive error: {e}")
            time.sleep(1)

def local_translate_pipeline(my_lang, target_lang):
    while not stop_event.is_set():
        if speaking_event.is_set():   # 👂 Skip listening if TTS is speaking
            time.sleep(0.1)
            continue
        try:
            st.info("🎤 Listening locally...")
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                if stop_event.is_set():
                    break
                audio = recognizer.listen(source, phrase_time_limit=6, timeout=3)

            if stop_event.is_set() or speaking_event.is_set():
                continue

            text = recognizer.recognize_google(audio, language=my_lang)
            st.write(f"🗣 You said ({LANGS[my_lang]}): {text}")

            translated = GoogleTranslator(source=my_lang, target=target_lang).translate(text)
            st.write(f"🌐 Translated → ({LANGS[target_lang]}): {translated}")

            st.success(f"🔊 Speaking ({LANGS[target_lang]}): {translated}")
            clear_tts_queue()
            tts_queue.put(translated)
            time.sleep(0.1)
        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            st.warning("🤔 Didn’t catch that.")
        except Exception as e:
            if not stop_event.is_set():
                st.error(f"⚠️ Local pipeline error: {e}")
            time.sleep(1)

# ---------------- Streamlit UI ----------------
def main():
    global current_tts_lang
    st.title("🌍 Real-Time Speech Translator")
    st.write("Translate + Speak between languages. Supports local & network modes.")

    if "running" not in st.session_state:
        st.session_state.running = False

    mode = st.radio("Select Mode", ["Same device", "Other device"])
    my_lang = st.selectbox("🌍 Pick your INPUT language", list(LANGS.keys()), format_func=lambda x: LANGS[x])
    st.radio("Voice Gender (not real in gTTS)", ["female", "male"], index=0)

    partner_ip = None
    target_lang = "en"
    if mode == "Same device":
        target_lang = st.selectbox("🌍 Pick your OUTPUT/TRANSLATION language", list(LANGS.keys()), index=0,
                                   format_func=lambda x: LANGS[x])
    else:
        partner_ip = st.text_input("💻 Partner IP (leave blank if unknown)")

    if st.button("🚀 Start Translator") and not st.session_state.running:
        stop_event.set()
        for t in active_threads:
            t.join(timeout=0.1)
        active_threads.clear()
        stop_event.clear()
        clear_tts_queue()

        current_tts_lang[0] = target_lang if mode == "Same device" else my_lang

        threading.Thread(target=tts_worker, daemon=True).start()

        if mode == "Same device":
            t = threading.Thread(target=local_translate_pipeline, args=(my_lang, target_lang), daemon=True)
            active_threads.append(t)
            t.start()
        else:
            sock = connect_auto(partner_ip, PORT)
            t1 = threading.Thread(target=listen_and_send, args=(sock, my_lang), daemon=True)
            t2 = threading.Thread(target=receive_translate_speak, args=(sock, my_lang), daemon=True)
            active_threads.extend([t1, t2])
            t1.start()
            t2.start()

        st.session_state.running = True
        st.success("✅ Translator running. Speak into your mic.")

    if st.session_state.running and st.button("🛑 Stop Translator"):
        stop_event.set()

        # 🔇 Kill any speech instantly
        clear_tts_queue()
        pygame.mixer.music.stop()
        speaking_event.clear()

        # 🔌 Kill all running threads
        for t in active_threads:
            t.join(timeout=0.2)
        active_threads.clear()

        st.session_state.running = False
        st.warning("⏹ Translator stopped. No input/output will be processed.")


if __name__ == "__main__":
    main()
'''

import socket
import threading
import speech_recognition as sr
from deep_translator import GoogleTranslator
import queue
import time
import uuid
from gtts import gTTS
import pygame
import os
import streamlit as st

# ---------------- Global Variables ----------------
PORT = 5001
recognizer = sr.Recognizer()
tts_queue = queue.Queue()
translator_instance = GoogleTranslator(source='auto', target='en')
LANGS = translator_instance.get_supported_languages(as_dict=True)
LANGS = {code: name.capitalize() for name, code in LANGS.items()}

stop_event = threading.Event()
active_threads = []
speaking_event = threading.Event()

# Init pygame mixer for non-blocking playback
pygame.mixer.init()

# Store the current TTS language globally
current_tts_lang = ["en"]


def clear_tts_queue():
    while not tts_queue.empty():
        try:
            tts_queue.get_nowait()
        except queue.Empty:
            break


# ---------------- TTS Worker ----------------
def tts_worker():
    while not stop_event.is_set():
        try:
            text = tts_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            filename = f"{uuid.uuid4()}.mp3"
            tts = gTTS(text=text, lang=current_tts_lang[0])
            tts.save(filename)

            speaking_event.set()  # 🔇 Block mic while speaking
            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                if stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.1)

            pygame.mixer.music.stop()
            speaking_event.clear()  # 🎤 Allow mic again
            os.remove(filename)
        except Exception as e:
            st.error(f"⚠️ TTS error: {e}")
            speaking_event.clear()


# ---------------- Local Translation Pipeline (Auto-Detect Input Language) ----------------
def local_translate_pipeline_auto(target_lang):
    while not stop_event.is_set():
        if speaking_event.is_set():  # 👂 Skip listening if TTS is speaking
            time.sleep(0.1)
            continue
        try:
            st.info("🎤 Listening... (auto-detect language)")
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                if stop_event.is_set():
                    break
                audio = recognizer.listen(source, phrase_time_limit=6, timeout=3)

            if stop_event.is_set() or speaking_event.is_set():
                continue

            # Step 1: Speech recognition (auto detect language)
            text = recognizer.recognize_google(audio)  # Auto-detect input
            st.write(f"🗣 You said: {text}")

            # Step 2: Translation (auto source detection)
            translator = GoogleTranslator(source='auto', target=target_lang)
            translated = translator.translate(text)
            try:
                detected_lang = translator.detect(text)
                detected_lang_name = LANGS.get(detected_lang, detected_lang).capitalize()
                st.write(f"🌐 Detected Language → {detected_lang_name}")
            except Exception:
                st.write("🌐 Detected Language → Unknown")

            st.write(f"🌐 Translated → ({LANGS[target_lang]}): {translated}")

            # Step 3: Speak the translated text
            st.success(f"🔊 Speaking ({LANGS[target_lang]}): {translated}")
            clear_tts_queue()
            tts_queue.put(translated)
            time.sleep(0.1)

        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            st.warning("🤔 Didn’t catch that.")
        except Exception as e:
            if not stop_event.is_set():
                st.error(f"⚠️ Auto pipeline error: {e}")
            time.sleep(1)


# ---------------- Streamlit UI ----------------
def main():
    global current_tts_lang
    st.title("🌍 Real-Time Speech Translator (Auto Language Detection)")
    st.write("Speak in any language — it auto-detects and translates to your chosen target language.")

    if "running" not in st.session_state:
        st.session_state.running = False

    target_lang = st.selectbox(
        "🌍 Pick your OUTPUT/TRANSLATION language",
        list(LANGS.keys()),
        index=0,
        format_func=lambda x: LANGS[x]
    )

    st.radio("Voice Gender (not real in gTTS)", ["female", "male"], index=0)

    if st.button("🚀 Start Translator") and not st.session_state.running:
        stop_event.set()
        for t in active_threads:
            t.join(timeout=0.1)
        active_threads.clear()
        stop_event.clear()
        clear_tts_queue()

        current_tts_lang[0] = target_lang

        threading.Thread(target=tts_worker, daemon=True).start()

        t = threading.Thread(target=local_translate_pipeline_auto, args=(target_lang,), daemon=True)
        active_threads.append(t)
        t.start()

        st.session_state.running = True
        st.success("✅ Translator running. Speak into your mic.")

    if st.session_state.running and st.button("🛑 Stop Translator"):
        stop_event.set()

        clear_tts_queue()
        pygame.mixer.music.stop()
        speaking_event.clear()

        for t in active_threads:
            t.join(timeout=0.2)
        active_threads.clear()

        st.session_state.running = False
        st.warning("⏹ Translator stopped. No input/output will be processed.")


if __name__ == "__main__":
    main()
