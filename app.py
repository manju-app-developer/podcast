import streamlit as st
import os
import asyncio
import json
import random
from google import genai
from google.genai import types
import edge_tts
from pydub import AudioSegment

# --- CONFIGURATION ---
MODEL_NAME = "gemini-2.5-flash"

# --- HELPER FUNCTIONS ---

def generate_podcast_script(topic, language, duration_minutes, api_key):
    """Generates the conversation script using Gemini."""
    client = genai.Client(api_key=api_key)
    
    # Podcast hosts speak about 160-170 words per minute
    target_word_count = duration_minutes * 170
    
    lang_instruction = "Write the dialogue in fluent, engaging English."
    if language == "Hindi":
        lang_instruction = "Write the dialogue in Hindi (using Devanagari script). Use English words for technical terms (Hinglish style) where natural."
    elif language == "Hinglish":
        lang_instruction = "Write the dialogue in Hinglish (Hindi spoken in English script), which is casual and popular in India."

    prompt = f"""
    You are the showrunner for a popular, high-energy tech podcast.
    Topic: {topic}
    Target Length: Approx {target_word_count} words.
    Language Instruction: {lang_instruction}
    
    Characters:
    1. Host 1 (Alex/Rahul): Skeptical, energetic, interrupts often, speaks in short punchy sentences.
    2. Host 2 (Sarah/Aditi): The expert, but explains things like a storyteller, not a professor.

    Format: RETURN ONLY A RAW JSON LIST of objects. Do not use Markdown code blocks.
    Structure: [{{ "speaker": "Host 1", "text": "Wait, seriously?" }}, {{ "speaker": "Host 2", "text": "Yes! And here is why..." }}]
    
    IMPORTANT: Write for the ear, not the eye. Use short sentences. Use "Umm", "Actually", "Wow", "Right?", to make it sound human.
    """

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=1.0 
            )
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Error generating script: {e}")
        return []

async def generate_audio_segment(text, voice, index, temp_dir="temp_audio"):
    """Generates a single audio segment using EdgeTTS with speed adjustments."""
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    output_file = os.path.join(temp_dir, f"seg_{index}.mp3")
    
    try:
        # rate="+15%" makes it sound like an excited podcaster
        # volume="+0%" keeps volume standard
        communicate = edge_tts.Communicate(text, voice, rate="+15%") 
        await communicate.save(output_file)
        return output_file
    except Exception as e:
        print(f"Error on segment {index}: {e}")
        return None

async def create_podcast_audio(script_json, language):
    """Orchestrates the creation of all audio segments."""
    
    # --- VOICE SELECTION (The "Realism" Upgrade) ---
    if language == "Hindi":
        voice_1 = "hi-IN-MadhurNeural" 
        voice_2 = "hi-IN-SwaraNeural"  
    elif language == "Hinglish":
        voice_1 = "en-IN-PrabhatNeural" 
        voice_2 = "en-IN-NeerjaNeural"
    else: # English - Using the best Multilingual voices for realism
        voice_1 = "en-US-AndrewMultilingualNeural" # Very realistic male
        voice_2 = "en-US-AvaMultilingualNeural"    # Very realistic female

    tasks = []
    
    progress_text = "🎙️ Recording... (Speed: 1.15x)"
    my_bar = st.progress(0, text=progress_text)

    for i, line in enumerate(script_json):
        speaker = line["speaker"]
        text = line["text"]
        
        if "Host 1" in speaker or "Alex" in speaker or "Rahul" in speaker:
            voice = voice_1
        else:
            voice = voice_2
            
        tasks.append(generate_audio_segment(text, voice, i))
    
    files = await asyncio.gather(*tasks)
    my_bar.progress(50, text="🎚️ Mixing and tightening gaps...")

    combined = AudioSegment.empty()
    valid_files = [f for f in files if f is not None]
    
    for file in valid_files:
        segment = AudioSegment.from_mp3(file)
        combined += segment
        # REDUCED SILENCE: 100ms (was 350ms). 
        # This makes it feel like they are in the same room.
        combined += AudioSegment.silent(duration=100) 
    
    # Cleanup
    for file in valid_files:
        try:
            os.remove(file)
        except:
            pass
            
    my_bar.progress(100, text="✅ Done!")
    return combined

# --- MAIN UI ---
def main():
    st.set_page_config(page_title="GenAI Podcaster", page_icon="🎧", layout="centered")

    st.title("🎧 AI Podcast Generator")
    st.caption("Powered by Gemini 2.0 & Neural Voice Engine")

    # --- SECURITY CHECK ---
    if "GEMINI_API_KEY" not in st.secrets:
        st.error("⚠️ Server Configuration Error: API Key missing. Please set GEMINI_API_KEY in Streamlit Secrets.")
        st.stop()
    
    api_key = st.secrets["GEMINI_API_KEY"]

    with st.sidebar:
        st.header("⚙️ Settings")
        language = st.selectbox("Language", ["English", "Hindi", "Hinglish"])
        duration = st.slider("Duration (Minutes)", 1, 10, 3)
        st.write("---")
        st.markdown("**Audio Style:**\n\n⚡ Fast Paced (+15%)\n\n🗣️ Natural Interruptions")
        
    topic = st.text_area("What should the podcast be about?", 
                         placeholder="e.g., The future of AI in India...", height=100)
    
    generate_btn = st.button("Generate Podcast 🚀", type="primary")

    if generate_btn and topic:
        
        # 1. Generate Script
        with st.spinner("🧠 Brainstorming a realistic script..."):
            script = generate_podcast_script(topic, language, duration, api_key)
        
        if script:
            with st.expander("📝 View Generated Script"):
                for line in script:
                    st.markdown(f"**{line['speaker']}:** {line['text']}")
            
            # 2. Generate Audio
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                final_audio = loop.run_until_complete(create_podcast_audio(script, language))
                
                # 3. Export
                output_filename = "podcast.mp3"
                final_audio.export(output_filename, format="mp3")
                
                st.audio(output_filename, format="audio/mp3")
                
                with open(output_filename, "rb") as file:
                    st.download_button(
                        label="📥 Download MP3",
                        data=file,
                        file_name=f"podcast_{topic[:10].replace(' ', '_')}.mp3",
                        mime="audio/mpeg"
                    )
                    
            except Exception as e:
                st.error(f"An error occurred during audio generation: {e}")

if __name__ == "__main__":
    main()

