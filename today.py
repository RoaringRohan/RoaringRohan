"""Render dark_mode.svg and light_mode.svg: ASCII portrait on the left, neofetch-style info on the right.

Public-repo GitHub stats are fetched from the GraphQL API when ACCESS_TOKEN is set; otherwise
the numbers already in the SVG are kept, so the static layout can be rebuilt offline.
"""
import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import escape, unescape

USER = os.environ.get('USER_NAME', 'RoaringRohan')
TOKEN = os.environ.get('ACCESS_TOKEN')
WIDTH = 60        # characters per info line
CHAR_W = 9.6      # px per character at 16px Consolas (with size-adjust) / DejaVu Sans Mono
LINE_H = 20
# Commits in these still count, but their lines don't: generated FPGA files, Unity assets, datasets.
LOC_EXCLUDE = {
    'RoaringRohan/fpga-academy-compute-acceleration',
    'RoaringRohan/taken-gino',
    'RoaringRohan/SE2250-Unity-Game-Taken-Gino-',
    'sukhmansra64/SE2250FinalGameProject',
    'RoaringRohan/data_analytics',
    'RoaringRohan/data-analytics-portfolio',
}
# Classroom orgs whose hundreds of assignment repos would swamp the Contributed count.
OWNER_EXCLUDE = {'ShaimaaAliECE'}
# The Action's token can't see org membership, so org repos are listed by hand.
# ponytail: static list, add new org repos here (or switch to a PAT with read:org).
ORG_REPOS = [
    'kang-lee-lab/long_to_short_dass', 'kang-lee-lab/lab-surveys',
    'WesternAlgo/Sigtech-Prj1', 'WesternAlgo/Sent-Analysis-Prj2-Twitter', 'WesternAlgo/Satellite-Imagery',
    'WesternAlgo/OptionsPricing', 'WesternAlgo/SovereignDebtDefault',
]

THEMES = {
    'dark_mode.svg':  dict(ascii='ascii_dark.txt', bg='#161b22', text='#c9d1d9', key='#ffa657', value='#a5d6ff', add='#3fb950', dele='#f85149', cc='#616e7f'),
    'light_mode.svg': dict(ascii='ascii_light.txt', bg='#f6f8fa', text='#24292f', key='#953800', value='#0a3069', add='#1a7f37', dele='#cf222e', cc='#c2cfde'),
}


def gql(query, **variables):
    req = urllib.request.Request(
        'https://api.github.com/graphql',
        data=json.dumps({'query': query, 'variables': variables}).encode(),
        headers={'Authorization': f'bearer {TOKEN}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.load(r)
    if body.get('errors'):
        raise RuntimeError(body['errors'])
    return body['data']


REPOS = '''query($login: String!, $aff: [RepositoryAffiliation], $cursor: String) {
  user(login: $login) {
    id
    repositories(first: 100, after: $cursor, ownerAffiliations: $aff, privacy: PUBLIC) {
      totalCount
      nodes { nameWithOwner }
      pageInfo { endCursor hasNextPage }
    }
  }
}'''

HISTORY = '''query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, after: $cursor, author: {id: $id}) {
        nodes { oid additions deletions }
        pageInfo { endCursor hasNextPage }
      }
    } } }
  }
}'''


def repos(affiliations):
    names, cursor = [], None
    while True:
        user = gql(REPOS, login=USER, aff=affiliations, cursor=cursor)['user']
        page = user['repositories']
        names += [n['nameWithOwner'] for n in page['nodes']]
        if not page['pageInfo']['hasNextPage']:
            return user['id'], page['totalCount'], names
        cursor = page['pageInfo']['endCursor']


def my_history(repo, user_id):
    """{commit oid: (additions, deletions)} for the user's commits on the repo's default branch."""
    owner, name = repo.split('/')
    commits, cursor = {}, None
    while True:
        ref = gql(HISTORY, owner=owner, name=name, id=user_id, cursor=cursor)['repository']['defaultBranchRef']
        if ref is None:  # empty repo
            return commits
        history = ref['target']['history']
        commits.update((n['oid'], (n['additions'], n['deletions'])) for n in history['nodes'])
        if not history['pageInfo']['hasNextPage']:
            return commits
        cursor = history['pageInfo']['endCursor']


def fetch_stats():
    user_id, owned, _ = repos(['OWNER'])
    _, _, names = repos(['OWNER', 'COLLABORATOR'])
    names = sorted({r for r in names + ORG_REPOS if r.split('/')[0] not in OWNER_EXCLUDE})
    contributed = len(names)
    commits = {}  # keyed by oid, so a commit living in a fork and its parent counts once
    with ThreadPoolExecutor(8) as pool:  # 8 keeps under GitHub's secondary rate limit
        for repo, repo_commits in zip(names, pool.map(lambda r: my_history(r, user_id), names)):
            commits.update({oid: (0, 0) for oid in repo_commits} if repo in LOC_EXCLUDE else repo_commits)
    added = sum(a for a, _ in commits.values())
    deleted = sum(d for _, d in commits.values())
    return dict(repos=owned, contrib=contributed, commits=len(commits), loc=added - deleted, loc_add=added, loc_del=deleted)


def stats_from_svg():
    """Reuse the numbers from the last render when there is no token."""
    try:
        with open('dark_mode.svg', encoding='utf-8') as f:
            svg = f.read()
    except FileNotFoundError:
        return dict(repos=0, contrib=0, commits=0, loc=0, loc_add=0, loc_del=0)
    return {k: int(re.search(f'id="{k}">([\\d,]+)<', svg).group(1).replace(',', ''))
            for k in ('repos', 'contrib', 'commits', 'loc', 'loc_add', 'loc_del')}


def span(cls, text, id=None):
    attrs = f' class="{cls}"' if cls else ''
    attrs += f' id="{id}"' if id else ''
    return f'<tspan{attrs}>{escape(text)}</tspan>'


def kv(keys, value):
    """'. Key.Sub: ..... value' padded with dots to WIDTH. value is a str or [(class, text, id?)]."""
    if isinstance(value, str):
        value = [('value', value)]
    used = 2 + len('.'.join(keys)) + 1 + sum(len(seg[1]) for seg in value)
    dots = max(WIDTH - used - 2, 1)
    return (span('cc', '. ') + '.'.join(span('key', k) for k in keys) + ':'
            + span('cc', ' ' + '.' * dots + ' ') + ''.join(span(*seg) for seg in value))


def title(text):
    return escape(text) + ' ' + '—' * (WIDTH - len(text) - 1)


def info_lines(s):
    n = lambda v: f'{v:,}'
    return [
        title('rohan@datta'),
        kv(['OS'], 'Windows, Linux'),
        kv(['Uptime'], '24 years'),
        kv(['Host'], 'University of Toronto'),
        kv(['Kernel'], "ECE Master's Program"),
        kv(['IDE'], 'VSCode'),
        span('cc', '. '),
        kv(['Languages', 'Programming'], 'Java, Python, JavaScript, Rust'),
        kv(['Languages', 'Computer'], 'SQL, YAML, JSON, HTML, CSS'),
        kv(['Languages', 'Real'], 'English, French, Hindi, Bengali'),
        span('cc', '. '),
        kv(['Hobbies', 'Real'], 'Chess, Table Tennis'),
        kv(['Hobbies', 'Hardware'], 'FPGA'),
        '',
        title('- Contact'),
        kv(['Email', 'School'], 'rohan.datta@mail.utoronto.ca'),
        kv(['Website'], 'rohandatta.ca'),
        kv(['LinkedIn'], 'dattarohan'),
        '',
        title('- GitHub Stats'),
        kv(['Repos'], [('value', n(s['repos']), 'repos'), (None, ' {'), ('key', 'Contributed'), (None, ': '),
                       ('value', n(s['contrib']), 'contrib'), (None, '}')]),
        kv(['Commits'], [('value', n(s['commits']), 'commits')]),
        kv(['Lines of Code on GitHub'], [('value', n(s['loc']), 'loc'), (None, ' ( '),
                                         ('addColor', n(s['loc_add']), 'loc_add'), ('addColor', '++'), (None, ', '),
                                         ('delColor', n(s['loc_del']), 'loc_del'), ('delColor', '--'), (None, ' )')]),
    ]


def render(theme, ascii_rows, info):
    ascii_cols = max(map(len, ascii_rows))
    info_cols = max(len(unescape(re.sub('<[^>]+>', '', line))) for line in info)
    info_x = 15 + round(ascii_cols * CHAR_W) + 25
    width = info_x + round(info_cols * CHAR_W) + 20
    height = max(len(ascii_rows), len(info)) * LINE_H + 25
    rows = max(len(ascii_rows), len(info))
    ascii_y = 30 + (rows - len(ascii_rows)) // 2 * LINE_H  # the shorter column is centered
    info_y = 30 + (rows - len(info)) // 2 * LINE_H
    t = theme
    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" '
        f'width="{width}px" height="{height}px" font-size="16px">',
        '<style>',
        "@font-face { src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback';"
        ' font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%; }',
        f'.key {{fill: {t["key"]};}} .value {{fill: {t["value"]};}} .addColor {{fill: {t["add"]};}}'
        f' .delColor {{fill: {t["dele"]};}} .cc {{fill: {t["cc"]};}} text, tspan {{white-space: pre;}}',
        '</style>',
        f'<rect width="{width}px" height="{height}px" fill="{t["bg"]}" rx="15"/>',
        f'<text x="15" y="{ascii_y}" fill="{t["text"]}">',
        *(f'<tspan x="15" y="{ascii_y + i * LINE_H}">{escape(row)}</tspan>' for i, row in enumerate(ascii_rows)),
        '</text>',
        f'<text x="{info_x}" y="{info_y}" fill="{t["text"]}">',
        *(f'<tspan x="{info_x}" y="{info_y + i * LINE_H}">{line}</tspan>' for i, line in enumerate(info) if line),
        '</text>',
        '</svg>',
    ]
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    stats = fetch_stats() if TOKEN else stats_from_svg()
    print(stats)
    info = info_lines(stats)
    for filename, theme in THEMES.items():
        with open(theme['ascii'], encoding='utf-8') as f:
            ascii_rows = f.read().rstrip('\n').split('\n')
        with open(filename, 'w', encoding='utf-8', newline='\n') as f:
            f.write(render(theme, ascii_rows, info))
