import socket
import threading
import speech_recognition as sr
from googletrans import Translator, LANGUAGES
import playsound
import os
import time
import sys
import keyboard
import openai

# ========= Available Languages =========
LANGS = {code: name.capitalize() for code, name in LANGUAGES.items()}
PORT = 5001
# ======================================

recognizer = sr.Recognizer()
translator = Translator()

# ---------- GenAI TTS helper ----------
def speak_genai(text, gender="male"):
    """
    Generate speech using OpenAI TTS with gendered voice.
    """
    voice = "alloy" if gender.lower() == "male" else "verse"
    try:
        audio = openai.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice=voice,
            input=text
        )
        filename = "recv.wav"
        with open(filename, "wb") as f:
            f.write(audio.read())
        playsound.playsound(filename)
        os.remove(filename)
    except Exception as e:
        print("⚠️ TTS error:", e)

# ---------- Language & IP selection ----------
def choose_language_and_ip():
    print("\n🌍 Auto language detection enabled.")
    my_lang = "en"  # Always translate *to* English (you can change)
    partner_ip = input("💻 Partner IP (leave blank if unknown): ").strip() or None
    gender = input("Select your voice gender (male/female): ").strip().lower() or "male"
    print(f"✅ Translation target: {LANGS[my_lang]} ({my_lang})")
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
            try:
                s.close()
            except:
                pass
        time.sleep(2)

# ---------- Audio pipelines ----------
def listen_and_send(sock):
    while True:
        try:
            print("⌨️ Hold SPACEBAR to talk...")
            keyboard.wait("space")
            print("🎤 Recording... release SPACEBAR when done.")

            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, phrase_time_limit=6)

            keyboard.wait("space")  # Wait until space released
            print("⏹️ Recording stopped.")

            # Recognize speech without specifying language
            text = recognizer.recognize_google(audio)
            detection = translator.detect(text)
            detected_lang = detection.lang
            confidence = detection.confidence * 100

            print(f"🗣 Detected: {LANGS.get(detected_lang, detected_lang)} ({confidence:.1f}% sure)")
            print(f"📝 You said: {text}")

            packet = f"{detected_lang}:{text}\n"
            sock.sendall(packet.encode("utf-8"))

        except sr.UnknownValueError:
            print("🤔 Didn’t catch that.")
        except Exception as e:
            print("⚠️ Mic/Send error:", e)
            time.sleep(1)

def receive_translate_speak(sock, my_lang, gender="male"):
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
                if not msg:
                    continue
                if ":" not in msg:
                    print("⚠️ Bad message:", msg)
                    continue

                src_lang, text = msg.split(":", 1)
                print(f"📥 Received ({LANGS.get(src_lang, src_lang)}): {text}")

                translated = translator.translate(text, src=src_lang, dest=my_lang).text
                print(f"🔊 Speaking ({LANGS[my_lang]}): {translated}")
                speak_genai(translated, gender)

        except Exception as e:
            print("⚠️ Receive error:", e)
            time.sleep(1)

# ---------- Main ----------
def main():
    my_lang, partner_ip, gender = choose_language_and_ip()
    sock = connect_auto(partner_ip, PORT)

    threading.Thread(target=listen_and_send, args=(sock,), daemon=True).start()
    threading.Thread(target=receive_translate_speak, args=(sock, my_lang, gender), daemon=True).start()

    print("\n✅ Translator running. Hold SPACEBAR to talk. Ctrl+C to exit.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Exiting…")
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except:
            pass
        sock.close()
        sys.exit(0)

if __name__ == "__main__":
    main()
