import socket
import threading
import speech_recognition as sr
from deep_translator import GoogleTranslator
import queue
import time
import sys
from gtts import gTTS
import playsound
import os
import uuid

PORT = 5001
recognizer = sr.Recognizer()

# ---------- Initialize TTS queue ----------
tts_queue = queue.Queue()

# ---------- TTS worker using gTTS ----------
def tts_worker(gender="female"):
    while True:
        text = tts_queue.get()
        if text is None:
            break  # exit signal
        try:
            filename = f"{uuid.uuid4()}.mp3"

            # Voice variant based on gender
            lang_code = "en"  # female default
            if gender == "male":
                lang_code = "en-us"  # male-ish variant

            tts = gTTS(text=text, lang=lang_code)
            tts.save(filename)
            playsound.playsound(filename, True)
            os.remove(filename)
        except Exception as e:
            print("⚠️ TTS error:", e)

# ---------- Language & IP selection ----------
translator_instance = GoogleTranslator(source='auto', target='en')
LANGS = translator_instance.get_supported_languages(as_dict=True)
LANGS = {code: name.capitalize() for name, code in LANGS.items()}

def choose_language_and_ip():
    print("\nLanguages:")
    for i, (code, name) in enumerate(LANGS.items(), 1):
        print(f"{i}. {name} ({code})")

    choice = input("\n🌍 Pick your language (number, code, or name): ").strip().lower()
    my_lang = "en"
    selected_name = LANGS[my_lang]

    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(LANGS):
            my_lang = list(LANGS.keys())[idx - 1]
            selected_name = LANGS[my_lang]
    elif choice in LANGS:
        my_lang = choice
        selected_name = LANGS[my_lang]
    else:
        for code, name in LANGS.items():
            if choice == name.lower():
                my_lang = code
                selected_name = name
                break

    gender = input("Select your voice gender (male/female): ").strip().lower()
    if gender not in ["male", "female"]:
        gender = "female"  # default fallback

    print(f"✅ You selected: {selected_name} ({my_lang}) with {gender} voice")
    partner_ip = input("💻 Partner IP (leave blank if unknown): ").strip() or None
    return my_lang, partner_ip, gender

# ---------- Networking ----------
def connect_auto(partner_ip, port):
    while True:
        if partner_ip:
            try:
                print(f"🔗 Trying client → {partner_ip}:{port} …")
                c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                c.settimeout(5)
                c.connect((partner_ip, port))
                c.settimeout(None)
                print("✅ Connected as client")
                return c
            except Exception as e:
                print(f"❌ Client connect failed: {e}")

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.settimeout(7)
            s.bind(("0.0.0.0", port))
            s.listen(1)
            print("📡 Listening as server for 7s…")
            conn, addr = s.accept()
            print("🤝 Partner connected from", addr)
            s.close()
            return conn
        except Exception as e:
            print(f"⏱ No incoming connection yet: {e}")
        finally:
            try: s.close()
            except: pass
        time.sleep(2)

# ---------- Audio pipelines ----------
def listen_and_send(sock, my_lang):
    while True:
        try:
            input("⌨️ Press ENTER to start talking...")
            print("🎤 Recording... speak now.")

            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, phrase_time_limit=6)

            print("⏹️ Recording stopped.")
            try:
                text = recognizer.recognize_google(audio, language=my_lang)
                print(f"🗣 You said ({LANGS[my_lang]}): {text}")
                packet = f"{my_lang}:{text}\n"
                sock.sendall(packet.encode("utf-8"))
            except sr.UnknownValueError:
                print("🤔 Didn’t catch that.")
            except Exception as e:
                print("⚠️ Mic/Send error:", e)
            time.sleep(0.1)
        except Exception as e:
            print("⚠️ Listen error:", e)
            time.sleep(1)

def receive_translate_speak(sock, my_lang):
    buffer = b""
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                print("🔌 Connection closed.")
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                msg = line.decode("utf-8", errors="replace").strip()
                if not msg or ":" not in msg:
                    continue
                src_lang, text = msg.split(":", 1)
                print(f"📥 Received ({LANGS.get(src_lang, src_lang)}): {text}")
                try:
                    translated = GoogleTranslator(source=src_lang, target=my_lang).translate(text)
                except Exception as e:
                    print("⚠️ Translation error:", e)
                    translated = text
                print(f"🔊 Speaking ({LANGS[my_lang]}): {translated}")
                tts_queue.put(translated)
        except Exception as e:
            print("⚠️ Receive error:", e)
            time.sleep(1)

# ---------- Main ----------
def main():
    my_lang, partner_ip, gender = choose_language_and_ip()
    sock = connect_auto(partner_ip, PORT)

    # Start TTS worker thread
    threading.Thread(target=tts_worker, args=(gender,), daemon=True).start()

    threading.Thread(target=listen_and_send, args=(sock, my_lang), daemon=True).start()
    threading.Thread(target=receive_translate_speak, args=(sock, my_lang), daemon=True).start()

    print("\n✅ Translator running. Press ENTER to talk. Ctrl+C to exit.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Exiting…")
        tts_queue.put(None)  # signal TTS worker to exit
        try: sock.shutdown(socket.SHUT_RDWR)
        except: pass
        sock.close()
        sys.exit(0)

if __name__ == "__main__":
    main()
