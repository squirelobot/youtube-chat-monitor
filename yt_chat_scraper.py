#!/usr/bin/env python3
"""
YouTube Live Chat scraper using innertube API.
Works for both live streams and chat replays, without cookies.

Usage:
  python3 yt_chat_scraper.py <VIDEO_ID_OR_URL> [--output chat.json]
"""

import requests
import json
import re
import sys
import time
import argparse
from datetime import datetime


def extract_video_id(url):
    for p in [r'(?:v=|/v/|youtu\.be/|/live/)([a-zA-Z0-9_-]{11})', r'^([a-zA-Z0-9_-]{11})$']:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return url


def get_initial_data(session, video_id):
    """Fetch live_chat page and extract initial messages + continuation."""
    r = session.get(f'https://www.youtube.com/live_chat?v={video_id}&is_popout=1')
    if r.status_code != 200:
        raise Exception(f"Failed: {r.status_code}")

    match = re.search(r'window\["ytInitialData"\]\s*=\s*(\{.*?\})\s*;', r.text, re.DOTALL)
    if not match:
        raise Exception("No ytInitialData found")

    data = json.loads(match.group(1))
    return data


def extract_messages_and_continuation(data):
    """Extract messages and next continuation from API response."""
    messages = []
    next_cont = None
    cont_type = None

    # Find actions - could be in different paths
    actions = []

    # Path 1: continuationContents (polling response)
    cc = data.get('continuationContents', {})
    lcc = cc.get('liveChatContinuation', {})
    if lcc:
        actions = lcc.get('actions', [])
        continuations = lcc.get('continuations', [])
    else:
        # Path 2: contents (initial page load)
        contents = data.get('contents', {})
        lcr = contents.get('liveChatRenderer', {})
        actions = lcr.get('actions', [])
        continuations = lcr.get('continuations', [])

    # Extract continuation token
    for c in continuations:
        for key in c:
            tok = c[key].get('continuation', '')
            if tok:
                next_cont = tok
                cont_type = key
                break

    # Extract messages
    for action in actions:
        replay = action.get('replayChatItemAction', action)
        sub_actions = replay.get('actions', [action])

        for sub in sub_actions:
            item = sub.get('addChatItemAction', {}).get('item', {})

            for renderer_key in ['liveChatTextMessageRenderer', 'liveChatPaidMessageRenderer']:
                renderer = item.get(renderer_key, {})
                if not renderer:
                    continue

                author = renderer.get('authorName', {}).get('simpleText', 'Unknown')
                ts_usec = renderer.get('timestampUsec', '0')
                timestamp = int(ts_usec) / 1_000_000

                runs = renderer.get('message', {}).get('runs', [])
                text = ''.join(
                    r.get('text', '')
                    if 'text' in r else
                    (r.get('emoji', {}).get('shortcuts', [''])[0] if r.get('emoji', {}).get('shortcuts') else
                     r.get('emoji', {}).get('emojiId', ''))
                    for r in runs
                )

                msg = {
                    'author': {'name': author},
                    'timestamp': timestamp,
                    'message': text,
                }

                if renderer_key == 'liveChatPaidMessageRenderer':
                    msg['superchat'] = renderer.get('purchaseAmountText', {}).get('simpleText', '')

                # Video offset for replays
                offset = replay.get('videoOffsetTimeMsec')
                if offset:
                    msg['offset_ms'] = int(offset)

                messages.append(msg)

    return messages, next_cont, cont_type


def main():
    parser = argparse.ArgumentParser(description='YouTube Live Chat Scraper')
    parser.add_argument('video', help='Video ID or URL')
    parser.add_argument('--output', '-o', default=None, help='Output JSON file')
    parser.add_argument('--duration', '-d', type=int, default=0, help='Max duration in seconds (0=unlimited, for live)')
    args = parser.parse_args()

    video_id = extract_video_id(args.video)
    output = args.output or f'chat_{video_id}.json'

    print(f"Video ID: {video_id}")
    print(f"Output: {output}")

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    })

    print("Fetching initial chat data...")
    data = get_initial_data(session, video_id)
    messages, continuation, cont_type = extract_messages_and_continuation(data)

    print(f"Initial: {len(messages)} messages, continuation type: {cont_type}")

    all_messages = list(messages)
    seen_timestamps = set((m['timestamp'], m['author']['name']) for m in messages)

    # Write initial messages
    with open(output, 'w', encoding='utf-8') as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + '\n')

    # Determine endpoint based on continuation type
    is_replay = cont_type and 'replay' in cont_type.lower()
    if is_replay:
        endpoint = 'live_chat/get_live_chat_replay'
    else:
        endpoint = 'live_chat/get_live_chat'

    api_key = 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8'
    page = 0
    start_time = time.time()

    print(f"Mode: {'replay' if is_replay else 'live'}")
    print(f"Polling for messages... (Ctrl+C to stop)")

    try:
        while continuation:
            page += 1

            if args.duration > 0 and time.time() - start_time > args.duration:
                print(f"\nDuration limit ({args.duration}s) reached")
                break

            url = f'https://www.youtube.com/youtubei/v1/{endpoint}?key={api_key}'
            payload = {
                'context': {'client': {'clientName': 'WEB', 'clientVersion': '2.20250210.01.00'}},
                'continuation': continuation,
            }

            try:
                r = session.post(url, json=payload, timeout=30)
                if r.status_code != 200:
                    print(f"  Page {page}: HTTP {r.status_code}, retrying...")
                    time.sleep(5)
                    continue

                data = r.json()
                new_msgs, continuation, cont_type = extract_messages_and_continuation(data)

                # Deduplicate
                unique_new = []
                for msg in new_msgs:
                    key = (msg['timestamp'], msg['author']['name'])
                    if key not in seen_timestamps:
                        seen_timestamps.add(key)
                        unique_new.append(msg)

                if unique_new:
                    with open(output, 'a', encoding='utf-8') as f:
                        for msg in unique_new:
                            f.write(json.dumps(msg, ensure_ascii=False) + '\n')
                    all_messages.extend(unique_new)

                elapsed = time.time() - start_time
                if page % 10 == 0 or (unique_new and page % 5 == 0):
                    print(f"  [{elapsed:.0f}s] Page {page}: +{len(unique_new)} new (total: {len(all_messages)})")

                if not continuation:
                    print("No more continuation — chat ended")
                    break

                # Rate limit
                if is_replay:
                    time.sleep(0.3)
                else:
                    time.sleep(3)  # Live: poll every 3s

            except requests.exceptions.Timeout:
                print(f"  Timeout on page {page}, retrying...")
                time.sleep(5)
            except Exception as e:
                print(f"  Error: {e}")
                time.sleep(5)

    except KeyboardInterrupt:
        print("\nStopped by user")

    print(f"\nDone! {len(all_messages)} messages saved to {output}")

    if all_messages:
        authors = set(m['author']['name'] for m in all_messages)
        print(f"Unique authors: {len(authors)}")
        from collections import Counter
        top = Counter(m['author']['name'] for m in all_messages).most_common(5)
        for name, count in top:
            print(f"  {name}: {count} msgs")


if __name__ == '__main__':
    main()
