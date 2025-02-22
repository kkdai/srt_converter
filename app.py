from flask import Flask, request, send_file, render_template, Response
from werkzeug.utils import secure_filename
import re
from datetime import datetime, timedelta
import io
from openai import OpenAI
import os
from pydub import AudioSegment
from pydub.silence import split_on_silence
import json
from threading import Lock
import time
import logging

# 設置日誌
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 檢查環境變數是否存在
if "OPENAI_API_KEY" not in os.environ:
    raise ValueError("請設定 OPENAI_API_KEY 環境變數")

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

app = Flask(__name__)

progress = {"lock": Lock(), "total_chunks": 0, "processed_chunks": 0}

def split_audio(file_path, chunk_length=600000):
    audio = AudioSegment.from_file(file_path)
    return [audio[i : i + chunk_length] for i in range(0, len(audio), chunk_length)]


def transcribe_audio(file_path):
    chunks = split_audio(file_path)
    
    with progress["lock"]:
        progress["total_chunks"] = len(chunks)
        progress["processed_chunks"] = 0
    
    full_transcript = []
    for i, chunk in enumerate(chunks):
        chunk_path = f"temp_chunk_{i}.mp3"
        chunk.export(chunk_path, format="mp3")
        
        with open(chunk_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-1",
                response_format="verbose_json"
            )
            
        time_offset = i * 10 * 60  # 10分鐘偏移
        
        # 使用正確的屬性訪問方式
        for segment in transcript.segments:
            adjusted_segment = {
                "start": float(segment.start) + time_offset,
                "end": float(segment.end) + time_offset,
                "text": segment.text
            }
            full_transcript.append(adjusted_segment)
            
        os.remove(chunk_path)
        
        with progress["lock"]:
            progress["processed_chunks"] = i + 1
            
    return full_transcript


def convert_to_srt(segments):
    srt_content = ""
    for i, segment in enumerate(segments, 1):
        start = timedelta(seconds=segment["start"])
        end = timedelta(seconds=segment["end"])
        text = segment["text"].strip()
        srt_content += f"{i}\n{_format_timestamp(start)} --> {_format_timestamp(end)}\n{text}\n\n"
    return srt_content


def _format_timestamp(delta: timedelta) -> str:
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    seconds = delta.seconds % 60
    milliseconds = delta.microseconds // 1000
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def convert_to_srt_file(file_path):
    # SRT轉換邏輯
    with open(file_path, "r") as file:
        content = file.read()
    # 將內容轉換為SRT格式
    srt_content = ""
    for line in content.split("\n"):
        match = re.search(
            r"(\d{2}:\d{2}:\d{2}),(\d{3}) --> (\d{2}:\d{2}:\d{2}),(\d{3})", line
        )
        if match:
            start_time = match.group(1) + "," + match.group(2)
            end_time = match.group(3) + "," + match.group(4)
            srt_content += f"{start_time} --> {end_time}\n"
    return srt_content


@app.route('/progress')
def progress_stream():
    def generate():
        while True:
            with progress["lock"]:
                if progress["total_chunks"] > 0:
                    percentage = (progress["processed_chunks"] / progress["total_chunks"]) * 100
                else:
                    percentage = 0
                
                data = {
                    "progress": percentage,
                    "processed": progress["processed_chunks"],
                    "total": progress["total_chunks"]
                }
                
            yield f"data: {json.dumps(data)}\n\n"
            time.sleep(1)
    
    return Response(generate(), mimetype='text/event-stream')


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/convert", methods=["POST"])
def convert():
    try:
        logger.debug("Starting convert function")
        
        if 'file' not in request.files:
            logger.error("No file part in request")
            return 'No file uploaded', 400
        
        file = request.files['file']
        logger.debug(f"Received file: {file.filename}")
        
        if file.filename == '':
            logger.error("No selected file")
            return 'No file selected', 400
        
        if not file.filename.lower().endswith(('.mp3', '.wav', '.m4a')):
            logger.error(f"Invalid file type: {file.filename}")
            return 'Invalid file type', 400
        
        # Reset progress
        with progress["lock"]:
            progress["total_chunks"] = 0
            progress["processed_chunks"] = 0
        
        filename = secure_filename(file.filename)
        file_path = os.path.join("uploads", filename)
        logger.debug(f"Saving file to: {file_path}")
        
        os.makedirs("uploads", exist_ok=True)
        file.save(file_path)
        
        logger.debug("Starting audio transcription")
        try:
            transcript = transcribe_audio(file_path)
            logger.debug(f"Transcription completed, segments: {len(transcript)}")
            
            logger.debug("Converting to SRT format")
            srt_content = convert_to_srt(transcript)
            logger.debug("SRT conversion completed")
            
            output = io.StringIO()
            output.write(srt_content)
            output.seek(0)
            
            logger.debug("Cleaning up temporary file")
            os.remove(file_path)
            
            logger.debug("Sending response")
            return send_file(
                output,
                mimetype='text/plain',
                as_attachment=True,
                download_name=f"{os.path.splitext(filename)[0]}.srt"
            )
            
        except Exception as e:
            logger.error(f"Error during transcription/conversion: {str(e)}", exc_info=True)
            if os.path.exists(file_path):
                os.remove(file_path)
            return f"處理錯誤: {str(e)}", 500
            
    except Exception as e:
        logger.error(f"Unexpected error in convert function: {str(e)}", exc_info=True)
        return f"系統錯誤: {str(e)}", 500


if __name__ == "__main__":
    app.run(debug=True)
