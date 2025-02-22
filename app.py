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

# 檢查環境變數是否存在
if "OPENAI_API_KEY" not in os.environ:
    raise ValueError("請設定 OPENAI_API_KEY 環境變數")

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

app = Flask(__name__)


def split_audio(file_path, chunk_length=600000):
    audio = AudioSegment.from_file(file_path)
    return [audio[i : i + chunk_length] for i in range(0, len(audio), chunk_length)]


def transcribe_audio(file_path):
    chunks = split_audio(file_path)
    full_transcript = []

    for i, chunk in enumerate(chunks):
        chunk_path = f"temp_chunk_{i}.mp3"
        chunk.export(chunk_path, format="mp3")

        with open(chunk_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-1",
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        time_offset = i * 10 * 60
        for segment in transcript.segments:
            adjusted_segment = {
                "start": segment["start"] + time_offset,
                "end": segment["end"] + time_offset,
                "text": segment["text"],
            }
            full_transcript.append(adjusted_segment)

        os.remove(chunk_path)

    return full_transcript


def convert_to_srt(segments):
    srt_content = ""
    for i, segment in enumerate(segments, 1):
        start = timedelta(seconds=segment["start"])
        end = timedelta(seconds=segment["end"])
        srt_content += f"{i}\n{_format_timestamp(start)} --> {_format_timestamp(end)}\n{segment['text']}\n\n"
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/convert", methods=["POST"])
def convert():
    file = request.files["file"]
    file_path = secure_filename(file.filename)
    file.save(file_path)
    # srt_content = convert_to_srt_file(file_path)
    transcript = transcribe_audio(file_path)
    srt_content = convert_to_srt(transcript)
    return send_file(
        io.BytesIO(srt_content.encode()),
        as_attachment=True,
        attachment_filename="output.srt",
    )


if __name__ == "__main__":
    app.run(debug=True)
