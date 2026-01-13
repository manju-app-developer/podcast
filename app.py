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
# 1. Get API Key from Streamlit Secrets or User Input
# Ideally set this in .streamlit/secrets.toml
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    API_KEY = ""  # Will prompt user in UI if missing

# Using the latest fast experimental model
MODEL_NAME = "gemini-2.0-flash-exp"

# --- HELPER FUNCTIONS ---

def generate_podcast_script(topic, language, duration_minutes, api_key):
    """Generates the conversation script using Gemini."""
    if not api_key:
        st.error("❌ API Key is missing.")
        return []

    client = genai.Client(api_key=api_key)
    
    # Estimate word count (approx 150 words per minute)
    target_word_count = duration_minutes * 150
    
    lang_instruction = "Write the dialogue in fluent, engaging English."
    if language == "Hindi":
        lang_instruction = "Write the dialogue in Hindi (using Devanagari script). You can use English words for technical terms (Hinglish style) where natural."
    elif language == "Hinglish":
        lang_instruction = "Write the dialogue in Hinglish (Hindi spoken in English script), which is casual and popular in India."

    prompt = f"""
    You are the showrunner for a popular podcast.
    Topic: {topic}
    Target Length: Approx {target_word_count} words.
    Language Instruction: {lang_instruction}
    
    Characters:
    1. Host 1 (Alex/Rahul): Energetic, curious, plays the 'audience' role.
    2. Host 2 (Sarah/Aditi): Expert, calm, insightful.

    Format: RETURN ONLY A RAW JSON LIST of objects. Do not use Markdown code blocks.
    Structure: [{{ "speaker": "Host 1", "text": "..." }}, {{ "speaker": "Host 2", "text": "..." }}]
    
    Make it sound natural. Use interruptions, "hmm", "actually", and "wow".
    """

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=1.0 # High creativity
            )
        )
        return json.loads(response.text)
    except Exception as e:
        st.error(f"Error generating script: {e}")
        return []

async def generate_audio_segment(text, voice, index, temp_dir="temp_audio"):
    """Generates a single audio segment using EdgeTTS."""
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
        
    output_file = os.path.join(temp_dir, f"seg_{index}.mp3")
    
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_file)
        return output_file
    except Exception as e:
        print(f"Error on segment {index}: {e}")
        return None

async def create_podcast_audio(script_json, language):
    """Orchestrates the creation of all audio segments."""
    
    # Voice Selection
    if language == "Hindi":
        voice_1 = "hi-IN-MadhurNeural" # Male
        voice_2 = "hi-IN-SwaraNeural"  # Female
    elif language == "Hinglish":
         # Indian English voices work best for Hinglish
        voice_1 = "en-IN-PrabhatNeural" 
        voice_2 = "en-IN-NeerjaNeural"
    else: # English
        voice_1 = "en-US-BrianMultilingualNeural" # Deep Male
        voice_2 = "en-US-AriaNeural"              # Clear Female

    tasks = []
    
    # Progress bar setup in Streamlit
    progress_text = "🎙️ Synthesizing voice segments..."
    my_bar = st.progress(0, text=progress_text)

    for i, line in enumerate(script_json):
        speaker = line["speaker"]
        text = line["text"]
        
        # Determine voice based on speaker tag
        # We assume Host 1 is usually the first speaker or identified by name
        if "Host 1" in speaker or "Alex" in speaker or "Rahul" in speaker:
            voice = voice_1
        else:
            voice = voice_2
            
        tasks.append(generate_audio_segment(text, voice, i))
    
    # Run all TTS tasks concurrently
    files = await asyncio.gather(*tasks)
    my_bar.progress(50, text="🎚️ Mixing audio...")

    # Merge Audio using Pydub
    combined = AudioSegment.empty()
    valid_files = [f for f in files if f is not None]
    
    for file in valid_files:
        segment = AudioSegment.from_mp3(file)
        combined += segment
        # Add a tiny natural pause between speakers
        combined += AudioSegment.silent(duration=350) 
    
    # Cleanup temp files
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
    st.write("Turn any topic into a professional podcast instantly.")

    # Sidebar for Configuration
    with st.sidebar:
        st.header("⚙️ Settings")
        
        # API Key Input
        user_api_key = st.text_input("Gemini API Key", type="password", value=API_KEY)
        if not user_api_key:
            st.warning("Please enter your Gemini API Key to proceed.")
            st.markdown("[Get API Key](https://aistudio.google.com/)")

        language = st.selectbox("Language", ["English", "Hindi", "Hinglish"])
        duration = st.slider("Duration (Minutes)", 1, 10, 3)
        
    # Main Input Area
    topic = st.text_area("What should the podcast be about?", 
                         placeholder="e.g., How to build a billion dollar company solo...", height=100)
    
    generate_btn = st.button("Generate Podcast 🚀", type="primary")

    if generate_btn and topic and user_api_key:
        
        # 1. Generate Script
        with st.spinner("🧠 Brainstorming the script..."):
            script = generate_podcast_script(topic, language, duration, user_api_key)
        
        if script:
            # Show the script in an expander
            with st.expander("📝 View Generated Script"):
                for line in script:
                    st.markdown(f"**{line['speaker']}:** {line['text']}")
            
            # 2. Generate Audio
            # We use a new event loop for asyncio compatibility in Streamlit
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                final_audio = loop.run_until_complete(create_podcast_audio(script, language))
                
                # 3. Export and Play
                output_filename = "podcast.mp3"
                final_audio.export(output_filename, format="mp3")
                
                st.audio(output_filename, format="audio/mp3")
                
                # Download Button
                with open(output_filename, "rb") as file:
                    st.download_button(
                        label="📥 Download Podcast",
                        data=file,
                        file_name=f"podcast_{topic[:10].replace(' ', '_')}.mp3",
                        mime="audio/mpeg"
                    )
                    
            except Exception as e:
                st.error(f"An error occurred during audio generation: {e}")

if __name__ == "__main__":
    main()
