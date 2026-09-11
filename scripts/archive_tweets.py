"""Import local X tweet archives as data; retrieve small relevant text samples."""
import argparse
import collections
import datetime as dt
import html
import json
from pathlib import Path
import re
import statistics
import unicodedata
import zipfile


def parse_data(raw):
    text = raw.decode('utf-8-sig').strip()
    if text.startswith('window.YTD.'):
        text = text.split('=', 1)[1].strip()
    data = json.loads(text.rstrip(';').rstrip())
    if not isinstance(data, list):
        raise ValueError('Expected an array of tweets')
    return data


def load_archive(path):
    if path.suffix.lower() != '.zip':
        return parse_data(path.read_bytes())
    rows = []
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            # Read just the tweet dataset, never execute JS or extract the ZIP.
            if re.search(r'(?:^|/)data/tweets(?:-part\d+)?\.js$', name):
                rows.extend(parse_data(archive.read(name)))
    if not rows:
        raise ValueError('No tweets found in data/tweets.js or tweets-part*.js')
    return rows


def normalized_rows(rows):
    kept = {}
    retweets = 0
    for wrapper in rows:
        tweet = wrapper.get('tweet', wrapper)
        text = html.unescape(tweet.get('full_text') or tweet.get('text') or '').strip()
        ident = str(tweet.get('id_str') or tweet.get('id') or '')
        if not ident or not text:
            continue
        if text.startswith('RT @') or tweet.get('retweeted_status'):
            retweets += 1
            continue
        reply_id = tweet.get('in_reply_to_status_id_str') or tweet.get('in_reply_to_status_id')
        # Old archives often omit reply metadata on addressed tweets.
        addressed = bool(re.match(r'^@\w+', text))
        kind = 'reply' if reply_id or addressed else 'quote' if tweet.get('is_quote_status') in (True, 'true') else 'post'
        created = tweet.get('created_at', '')
        try:
            created = dt.datetime.strptime(created, '%a %b %d %H:%M:%S %z %Y').isoformat()
        except ValueError:
            pass
        kept[ident] = dict(id=ident, created_at=created, text=text, kind=kind,
                           reply_inferred=bool(addressed and not reply_id), lang=tweet.get('lang'),
                           likes=int(tweet.get('favorite_count') or 0),
                           reposts=int(tweet.get('retweet_count') or 0))
    return sorted(kept.values(), key=lambda t: t['created_at'], reverse=True), retweets


def import_archive(args):
    source = Path(args.archive).resolve()
    account = getattr(args, 'account', None)
    account = account.strip().lstrip('@') if account else None
    if account and not re.fullmatch(r'[A-Za-z0-9_]{1,15}', account):
        raise ValueError('Expected an X username for --account')
    account_verified = False
    if account and source.suffix.lower() == '.zip':
        with zipfile.ZipFile(source) as archive:
            names = [n for n in archive.namelist() if re.search(r'(?:^|/)data/account\.js$', n)]
            if len(names) != 1:
                raise ValueError('Cannot verify account: expected one data/account.js in ZIP')
            accounts = parse_data(archive.read(names[0]))
            handles = {item.get('account', {}).get('username', '').lower() for item in accounts}
            if handles != {account.lower()}:
                raise ValueError('Archive account does not match --account; existing corpus untouched')
            account_verified = True
    raw = load_archive(source)
    rows, retweets = normalized_rows(raw)
    if not rows:
        raise ValueError('No authored tweets found; existing corpus left untouched')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    summary = dict(source=str(source), imported_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                   account=account, account_verified=account_verified, source_type='archive',
                   archive_rows=len(raw), authored_tweets=len(rows), retweets_excluded=retweets,
                   kinds=dict(collections.Counter(t['kind'] for t in rows)),
                   inferred_replies=sum(t['reply_inferred'] for t in rows),
                   languages=dict(collections.Counter(t['lang'] or 'unknown' for t in rows)),
                   earliest=min(t['created_at'] for t in rows), latest=max(t['created_at'] for t in rows),
                   median_characters=statistics.median(len(t['text']) for t in rows),
                   limitations=['Replies inferred from an initial mention may include addressed standalone posts.',
                                'Archive snapshot only; not current account activity or opinions.',
                                'Separate note-tweet and community-tweet datasets are not imported.',
                                'Media content and the other side of conversations are not analyzed.'])
    (out / 'tweets.jsonl').write_text(''.join(json.dumps(t, ensure_ascii=False) + '\n' for t in rows), encoding='utf-8')
    (out / 'corpus-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))


def search(args):
    terms = fold(args.query).split()
    results = []
    with Path(args.corpus).open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            if args.kind and row['kind'] != args.kind:
                continue
            score = sum(term in fold(row['text']) for term in terms)
            if terms and not score:
                continue
            results.append((score, row['created_at'], row))
    for _, _, row in sorted(results, key=lambda r: (r[0], r[1]), reverse=True)[:args.limit]:
        print(json.dumps(row, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    imp = sub.add_parser('import')
    imp.add_argument('--archive', required=True)
    imp.add_argument('--output', required=True)
    imp.add_argument('--account', help='Target X username; verified against data/account.js for ZIP archives')
    imp.set_defaults(func=import_archive)
    find = sub.add_parser('search')
    find.add_argument('--corpus', required=True)
    find.add_argument('--query', default='')
    find.add_argument('--kind', choices=['post', 'reply', 'quote'])
    find.add_argument('--limit', type=int, default=8)
    find.set_defaults(func=search)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
