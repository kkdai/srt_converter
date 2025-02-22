from flask import Flask, request, send_file, render_template
from werkzeug.utils import secure_filename
import re
from datetime import datetime, timedelta
import io
from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = Flask(__name__)


def convert_to_srt(file_path):
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


@app.route('/')
def index():
    return render_template('index.html')


@app.route("/convert", methods=["POST"])
def convert():
    file = request.files["file"]
    file_path = secure_filename(file.filename)
    file.save(file_path)
    srt_content = convert_to_srt(file_path)
    return send_file(
        io.BytesIO(srt_content.encode()),
        as_attachment=True,
        attachment_filename="output.srt",
    )


if __name__ == "__main__":
    app.run(debug=True)
