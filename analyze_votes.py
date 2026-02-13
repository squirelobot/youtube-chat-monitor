#!/usr/bin/env python3
"""
YouTube Live Chat Vote Analyzer
Participants vote by typing 1, 2, or 3 in chat.

Generates:
  1. Vote count per option over time (10s, 1min, 5min buckets) - stacked bars
  2. Cumulative votes over time - line chart
  3. Per-voter analysis (who voted what, vote changes)
  4. Final results pie chart

Usage:
  python3 analyze_votes.py <chat_log.json> [--output-dir DIR]
"""

import json
import sys
import os
import re
import argparse
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

VOTE_PATTERN = re.compile(r'^\s*([123])\s*$')
VOTE_COLORS = {'1': '#2196F3', '2': '#FF9800', '3': '#4CAF50'}
VOTE_LABELS = {'1': 'Vote 1', '2': 'Vote 2', '3': 'Vote 3'}


def load_messages(path):
    """Load chat_downloader or yt-dlp JSON."""
    messages = []
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read().strip()

    # JSONL
    if content.startswith('{'):
        for line in content.split('\n'):
            line = line.strip().rstrip(',')
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    else:
        try:
            messages = json.loads(content)
        except:
            try:
                messages = json.loads('[' + content + ']')
            except:
                pass

    # Also try yt-dlp nested format
    if messages and 'replayChatItemAction' in messages[0]:
        converted = []
        for obj in messages:
            try:
                actions = obj['replayChatItemAction'].get('actions', [])
                for action in actions:
                    item = action.get('addChatItemAction', {}).get('item', {})
                    renderer = item.get('liveChatTextMessageRenderer', {})
                    if renderer:
                        author = renderer.get('authorName', {}).get('simpleText', 'Unknown')
                        ts = int(renderer.get('timestampUsec', '0')) / 1_000_000
                        text_runs = renderer.get('message', {}).get('runs', [])
                        text = ''.join(r.get('text', '') for r in text_runs)
                        converted.append({'author': {'name': author}, 'timestamp': ts, 'message': text})
            except:
                continue
        messages = converted

    return messages


def extract_votes(messages):
    """Extract vote messages and normalize."""
    votes = []
    for msg in messages:
        author = msg.get('author', {})
        if isinstance(author, dict):
            name = author.get('name', 'Unknown')
        else:
            name = str(author)

        text = str(msg.get('message', msg.get('text', '')))
        match = VOTE_PATTERN.match(text)
        if not match:
            continue

        vote = match.group(1)

        ts = msg.get('timestamp', msg.get('time_in_seconds', 0))
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts)
            except:
                continue
        elif isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1_000_000
            if ts > 1e9:
                dt = datetime.utcfromtimestamp(ts)
            else:
                dt = datetime(2000, 1, 1) + timedelta(seconds=ts)
        else:
            continue

        votes.append((dt, name, vote))

    votes.sort(key=lambda x: x[0])
    return votes


def build_vote_df(votes):
    df = pd.DataFrame(votes, columns=['timestamp', 'author', 'vote'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def plot_votes_bucketed(df, bucket_seconds, title_suffix, output_path):
    """Stacked bar: vote counts per bucket."""
    if df.empty:
        return

    start = df['timestamp'].min()
    df2 = df.copy()
    df2['bucket'] = ((df2['timestamp'] - start).dt.total_seconds() // bucket_seconds).astype(int)

    pivot = df2.groupby(['bucket', 'vote']).size().unstack(fill_value=0)
    # Ensure all vote columns exist
    for v in ['1', '2', '3']:
        if v not in pivot.columns:
            pivot[v] = 0
    pivot = pivot[['1', '2', '3']]
    pivot.index = [start + timedelta(seconds=int(b) * bucket_seconds) for b in pivot.index]

    fig, ax = plt.subplots(figsize=(16, 7))
    pivot.plot(kind='bar', stacked=True, ax=ax, color=[VOTE_COLORS['1'], VOTE_COLORS['2'], VOTE_COLORS['3']], width=0.9)

    ax.set_title(f'Votes par période ({title_suffix})', fontsize=14, fontweight='bold')
    ax.set_xlabel('Temps', fontsize=12)
    ax.set_ylabel('Nombre de votes', fontsize=12)

    n_ticks = min(25, len(pivot))
    step = max(1, len(pivot) // n_ticks)
    tick_positions = range(0, len(pivot), step)
    tick_labels = [pivot.index[i].strftime('%H:%M:%S') for i in tick_positions]
    ax.set_xticks(list(tick_positions))
    ax.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=9)

    ax.legend([VOTE_LABELS['1'], VOTE_LABELS['2'], VOTE_LABELS['3']], fontsize=11)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path}")


def plot_cumulative_votes(df, output_path):
    """Line chart: cumulative votes over time."""
    if df.empty:
        return

    fig, ax = plt.subplots(figsize=(16, 7))

    for vote in ['1', '2', '3']:
        vote_df = df[df['vote'] == vote].copy().sort_values('timestamp')
        if vote_df.empty:
            continue
        vote_df['cumcount'] = range(1, len(vote_df) + 1)
        ax.plot(vote_df['timestamp'], vote_df['cumcount'],
                label=VOTE_LABELS[vote], color=VOTE_COLORS[vote], linewidth=2.5)

    ax.set_title('Votes cumulés au cours du temps', fontsize=14, fontweight='bold')
    ax.set_xlabel('Temps', fontsize=12)
    ax.set_ylabel('Votes cumulés', fontsize=12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.legend(fontsize=12)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path}")


def plot_final_pie(df, output_path):
    """Pie chart of final results (last vote per person)."""
    if df.empty:
        return

    # Only count LAST vote per person
    last_votes = df.sort_values('timestamp').groupby('author').last()['vote']
    counts = last_votes.value_counts().reindex(['1', '2', '3'], fill_value=0)

    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        counts.values,
        labels=[f"{VOTE_LABELS[v]}\n{c} votes ({c/max(counts.sum(),1)*100:.1f}%)" for v, c in counts.items()],
        colors=[VOTE_COLORS[v] for v in counts.index],
        autopct='',
        startangle=90,
        textprops={'fontsize': 13}
    )
    ax.set_title(f'Résultat final ({counts.sum()} votants uniques)', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path}")


def plot_vote_changes(df, output_path):
    """Show voters who changed their vote."""
    if df.empty:
        return

    changers = []
    for author, group in df.sort_values('timestamp').groupby('author'):
        votes_list = group['vote'].tolist()
        if len(set(votes_list)) > 1:
            changers.append({
                'author': author,
                'votes': ' → '.join(votes_list),
                'first': votes_list[0],
                'last': votes_list[-1],
                'count': len(votes_list),
            })

    if not changers:
        print("  No vote changes detected")
        return

    changers.sort(key=lambda x: x['count'], reverse=True)

    fig, ax = plt.subplots(figsize=(12, max(4, len(changers[:30]) * 0.4)))
    ax.axis('off')

    table_data = [[c['author'], c['votes'], c['count']] for c in changers[:30]]
    table = ax.table(
        cellText=table_data,
        colLabels=['Participant', 'Historique votes', 'Nb votes'],
        cellLoc='center',
        loc='center',
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.5)
    ax.set_title(f'Changements de vote ({len(changers)} personnes)', fontsize=14, fontweight='bold', pad=20)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: {output_path}")


def print_stats(df, all_msgs_count):
    """Print vote statistics."""
    print(f"\n{'='*50}")
    print(f"  STATISTIQUES DE VOTE")
    print(f"{'='*50}")
    print(f"  Messages totaux dans le chat : {all_msgs_count}")
    print(f"  Messages de vote (1/2/3)     : {len(df)}")
    print(f"  Votants uniques              : {df['author'].nunique()}")

    if df.empty:
        return

    duration = df['timestamp'].max() - df['timestamp'].min()
    print(f"  Durée du vote                : {duration}")
    print(f"  Votes/min                    : {len(df) / max(duration.total_seconds()/60, 1):.1f}")

    # Last vote per person (final results)
    last_votes = df.sort_values('timestamp').groupby('author').last()['vote']
    counts = last_votes.value_counts().reindex(['1', '2', '3'], fill_value=0)

    print(f"\n  --- RÉSULTATS FINAUX (dernier vote par personne) ---")
    total = counts.sum()
    for v in ['1', '2', '3']:
        bar = '█' * int(counts[v] / max(total, 1) * 40)
        print(f"  Vote {v}: {counts[v]:5d} ({counts[v]/max(total,1)*100:5.1f}%)  {bar}")

    winner = counts.idxmax()
    print(f"\n  🏆 GAGNANT : Vote {winner} avec {counts[winner]} votes ({counts[winner]/total*100:.1f}%)")

    # Multi-voters
    vote_counts = df.groupby('author').size()
    multi = (vote_counts > 1).sum()
    print(f"\n  Personnes ayant voté plusieurs fois : {multi}")

    # Changers
    changers = 0
    for author, group in df.sort_values('timestamp').groupby('author'):
        if group['vote'].nunique() > 1:
            changers += 1
    print(f"  Personnes ayant changé de vote     : {changers}")


def main():
    parser = argparse.ArgumentParser(description='YouTube Live Chat Vote Analyzer')
    parser.add_argument('input', help='Chat log JSON file')
    parser.add_argument('--output-dir', '-o', default=None, help='Output directory')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: {args.input} not found")
        sys.exit(1)

    output_dir = args.output_dir or os.path.join(os.path.dirname(args.input) or '.', 'vote_results')
    os.makedirs(output_dir, exist_ok=True)

    print(f"Loading {args.input}...")
    messages = load_messages(args.input)
    print(f"Total messages: {len(messages)}")

    votes = extract_votes(messages)
    print(f"Vote messages (1/2/3): {len(votes)}")

    df = build_vote_df(votes)
    print_stats(df, len(messages))

    print("\nGenerating graphs...")
    base = Path(output_dir)

    # Vote counts per bucket
    for secs, label, filename in [
        (10, '10 secondes', 'votes_10s.png'),
        (60, '1 minute', 'votes_1min.png'),
        (300, '5 minutes', 'votes_5min.png'),
    ]:
        plot_votes_bucketed(df, secs, label, str(base / filename))

    # Cumulative
    plot_cumulative_votes(df, str(base / 'votes_cumulative.png'))

    # Final pie
    plot_final_pie(df, str(base / 'votes_final.png'))

    # Vote changes
    plot_vote_changes(df, str(base / 'vote_changes.png'))

    # Save raw vote data CSV
    csv_path = str(base / 'votes.csv')
    df.to_csv(csv_path, index=False)
    print(f"  Saved: {csv_path}")

    print(f"\nDone! All outputs in {output_dir}")


if __name__ == '__main__':
    main()
