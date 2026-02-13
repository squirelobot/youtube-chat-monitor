#!/usr/bin/env python3
"""
YouTube Live Chat Backup - Multiple methods for redundancy.

Runs up to 3 capture methods in parallel to ensure no messages are lost:
  1. Innertube API scraper (no cookies needed) — PRIMARY
  2. chat_downloader library (no cookies needed) — BACKUP 1
  3. yt-dlp (may need cookies on some IPs) — BACKUP 2

Each method saves to its own file. A merge script combines them.

Usage:
  python3 yt_chat_backup.py <VIDEO_URL> [--duration SECONDS] [--output-dir DIR]
"""

import subprocess
import sys
import os
import json
import time
import signal
import argparse
from datetime import datetime
from pathlib import Path


def run_innertube(video_url, output_path, duration):
    """Method 1: Custom innertube scraper (most reliable, no cookies)."""
    cmd = [sys.executable, '-u', 'yt_chat_scraper.py', video_url, '-o', output_path]
    if duration:
        cmd += ['-d', str(duration)]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, bufsize=1)


def run_chat_downloader(video_url, output_path, duration):
    """Method 2: chat_downloader library."""
    script = f'''
import json, time, signal, sys
from chat_downloader import ChatDownloader

start = time.time()
duration = {duration or 0}

chat = ChatDownloader().get_chat("{video_url}", message_types=["text_message", "paid_message"])
count = 0

with open("{output_path}", "w", encoding="utf-8") as f:
    try:
        for msg in chat:
            if duration and time.time() - start > duration:
                break
            out = {{
                "author": {{"name": msg.get("author", {{}}).get("name", "Unknown")}},
                "timestamp": msg.get("timestamp", 0) / 1_000_000 if msg.get("timestamp", 0) > 1e12 else msg.get("timestamp", 0),
                "message": msg.get("message", ""),
            }}
            f.write(json.dumps(out, ensure_ascii=False) + "\\n")
            f.flush()
            count += 1
            if count % 100 == 0:
                print(f"[chat_downloader] {{count}} messages captured", flush=True)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[chat_downloader] Error: {{e}}", flush=True)

print(f"[chat_downloader] Done: {{count}} messages saved to {output_path}", flush=True)
'''
    return subprocess.Popen([sys.executable, '-u', '-c', script],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, bufsize=1)


def run_ytdlp(video_url, output_path, duration):
    """Method 3: yt-dlp live chat download."""
    # yt-dlp saves as .live_chat.json — we'll convert after
    base = output_path.replace('.json', '')
    cmd = ['yt-dlp', '--skip-download', '--write-sub', '--sub-lang', 'live_chat',
           '--output', base, video_url]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, bufsize=1)


def merge_chats(files, output_path):
    """Merge multiple JSONL chat files, deduplicate by (timestamp, author)."""
    seen = set()
    all_msgs = []

    for f in files:
        if not os.path.exists(f):
            continue
        with open(f, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    author = msg.get('author', {}).get('name', '')
                    ts = msg.get('timestamp', 0)
                    key = (round(ts, 1), author)
                    if key not in seen:
                        seen.add(key)
                        all_msgs.append(msg)
                except:
                    continue

    all_msgs.sort(key=lambda x: x.get('timestamp', 0))

    with open(output_path, 'w', encoding='utf-8') as f:
        for msg in all_msgs:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')

    return len(all_msgs)


def main():
    parser = argparse.ArgumentParser(description='YouTube Live Chat Backup (multi-method)')
    parser.add_argument('video', help='Video URL or ID')
    parser.add_argument('--duration', '-d', type=int, default=0, help='Max duration in seconds (0=unlimited)')
    parser.add_argument('--output-dir', '-o', default='chat_backup', help='Output directory')
    parser.add_argument('--methods', '-m', default='all',
                       help='Methods to use: all, innertube, chatdl, ytdlp (comma-separated)')
    args = parser.parse_args()

    outdir = Path(args.output_dir)
    outdir.mkdir(exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    methods_list = args.methods.split(',') if args.methods != 'all' else ['innertube', 'chatdl', 'ytdlp']

    processes = {}
    files = []

    print(f"{'='*60}")
    print(f"  YouTube Live Chat Backup")
    print(f"  Video: {args.video}")
    print(f"  Methods: {', '.join(methods_list)}")
    print(f"  Output: {outdir}/")
    print(f"{'='*60}\n")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    if 'innertube' in methods_list:
        f = str(outdir / f'chat_innertube_{ts}.json')
        files.append(f)
        try:
            p = run_innertube(args.video, f, args.duration)
            processes['innertube'] = p
            print(f"[+] Innertube scraper started (PID {p.pid})")
        except Exception as e:
            print(f"[-] Innertube failed to start: {e}")

    if 'chatdl' in methods_list:
        f = str(outdir / f'chat_chatdl_{ts}.json')
        files.append(f)
        try:
            p = run_chat_downloader(args.video, f, args.duration)
            processes['chat_downloader'] = p
            print(f"[+] chat_downloader started (PID {p.pid})")
        except Exception as e:
            print(f"[-] chat_downloader failed to start: {e}")

    if 'ytdlp' in methods_list:
        f = str(outdir / f'chat_ytdlp_{ts}.json')
        files.append(f)
        try:
            p = run_ytdlp(args.video, f, args.duration)
            processes['yt-dlp'] = p
            print(f"[+] yt-dlp started (PID {p.pid})")
        except Exception as e:
            print(f"[-] yt-dlp failed to start: {e}")

    if not processes:
        print("No capture methods could start!")
        sys.exit(1)

    print(f"\nCapturing... Press Ctrl+C to stop and merge.\n")

    # Monitor processes
    try:
        while processes:
            for name, p in list(processes.items()):
                line = p.stdout.readline()
                if line:
                    print(f"[{name}] {line.rstrip()}")
                if p.poll() is not None:
                    print(f"\n[{name}] Finished (exit code {p.returncode})")
                    del processes[name]
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nStopping all captures...")
        for name, p in processes.items():
            p.send_signal(signal.SIGINT)
            try:
                p.wait(timeout=5)
            except:
                p.kill()
            print(f"  [{name}] Stopped")

    # Merge all files
    merged_path = str(outdir / f'chat_MERGED_{ts}.json')
    print(f"\nMerging all captures...")
    total = merge_chats(files, merged_path)

    # Stats per file
    print(f"\n{'='*60}")
    print(f"  BACKUP SUMMARY")
    print(f"{'='*60}")
    for f in files:
        if os.path.exists(f):
            count = sum(1 for _ in open(f))
            print(f"  {os.path.basename(f)}: {count} messages")
        else:
            print(f"  {os.path.basename(f)}: NOT CREATED")
    print(f"  ---")
    print(f"  MERGED: {total} unique messages → {merged_path}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
