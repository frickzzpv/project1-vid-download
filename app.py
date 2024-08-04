# app.py

from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import sqlite3
from datetime import datetime, timedelta
import schedule
import time
import threading

app = Flask(__name__)

# Database setup
def get_db_connection():
    conn = sqlite3.connect('videos.db')
    conn.row_factory = sqlite3.Row
    return conn
 
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if the 'quality' column exists
    cursor.execute("PRAGMA table_info(videos)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'quality' not in columns:
        # Add the 'quality' column if it doesn't exist
        cursor.execute('ALTER TABLE videos ADD COLUMN quality TEXT')
        print("Added 'quality' column to the 'videos' table.")
    
    # Create the table if it doesn't exist
    cursor.execute('''CREATE TABLE IF NOT EXISTS videos
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     url TEXT NOT NULL,
                     filename TEXT NOT NULL,
                     quality TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

# Call init_db() at the start of your application

init_db()


# Video info function
def get_video_info(url):
    ydl_opts = {'format': 'bestaudio/best'}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        # Filter and group formats
        formats = {}
        for f in info['formats']:
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none':  # Only video with audio
                resolution = f.get('resolution', 'unknown')
                if resolution not in formats or f.get('filesize', 0) > formats[resolution].get('filesize', 0):
                    formats[resolution] = {
                        'format_id': f['format_id'],
                        'ext': f['ext'],
                        'resolution': resolution,
                        'filesize': f.get('filesize', 'N/A')
                    }
        
        # Sort formats by resolution (assuming format is "WIDTHxHEIGHT")
        sorted_formats = sorted(formats.values(), 
                                key=lambda x: int(x['resolution'].split('x')[1]) if 'x' in x['resolution'] else 0,
                                reverse=True)
        
        # Select a subset of formats (e.g., highest, high, medium, low)
        selected_formats = []
        if len(sorted_formats) > 0:
            selected_formats.append(sorted_formats[0])  # Highest quality
        if len(sorted_formats) > 2:
            selected_formats.append(sorted_formats[len(sorted_formats)//2])  # Medium quality
        if len(sorted_formats) > 1:
            selected_formats.append(sorted_formats[-1])  # Lowest quality
        
        return {'title': info['title'], 'formats': selected_formats}


# Video download function
def download_video(url, format_id):
    ydl_opts = {
        'format': format_id,
        'outtmpl': 'downloads/%(title)s.%(ext)s'
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    return filename

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_info', methods=['POST'])
def get_info():
    url = request.json['url']
    try:
        info = get_video_info(url)
        return jsonify(info)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/download', methods=['POST'])
def download():
    url = request.json['url']
    format_id = request.json['format_id']
    try:
        filename = download_video(url, format_id)
        quality = next((f['resolution'] for f in get_video_info(url)['formats'] if f['format_id'] == format_id), 'Unknown')
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO videos (url, filename, quality) VALUES (?, ?, ?)', (url, filename, quality))
        except sqlite3.OperationalError:
            # If 'quality' column doesn't exist, insert without it
            conn.execute('INSERT INTO videos (url, filename) VALUES (?, ?)', (url, filename))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'filename': os.path.basename(filename)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/get_file/<filename>')
def get_file(filename):
    return send_file(f'downloads/{filename}', as_attachment=True)

# Cleanup function (unchanged)
def cleanup_old_files():
    conn = get_db_connection()
    week_ago = datetime.now() - timedelta(days=7)
    old_videos = conn.execute('SELECT filename FROM videos WHERE created_at < ?', (week_ago,)).fetchall()
    for video in old_videos:
        try:
            os.remove(video['filename'])
            conn.execute('DELETE FROM videos WHERE filename = ?', (video['filename'],))
        except OSError:
            pass
    conn.commit()
    conn.close()

# Schedule cleanup
schedule.every().day.at("00:00").do(cleanup_old_files)

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    threading.Thread(target=run_schedule, daemon=True).start()
    app.run(debug=True)
