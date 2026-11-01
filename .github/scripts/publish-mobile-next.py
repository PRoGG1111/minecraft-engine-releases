#!/usr/bin/env python3
"""Mirror verified, publicly hosted Mobile Next APKs into GitHub Releases."""
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ORIGIN = 'https://minecraft-engine-social-progg1111.rockysnow18.chatgpt.site'
PIN = 'dc47265ed66fb3c8241b90f0d7eaca7195562e529ca03ef642cf27fe0389a28f'
REPOSITORY = 'PRoGG1111/minecraft-engine-releases'
FILES = ['MinecraftEngine-Android.apk', 'MinecraftEngine-Launcher.apk', 'android-feed.json']
AGENT = 'MinecraftEngine-MobileNext-Release/0.3'


def public_download(url, target, expected=None, maximum=200000000):
    assert url.startswith('https://')
    request = urllib.request.Request(url, headers={'User-Agent': AGENT})
    sha = hashlib.sha256(); size = 0
    with urllib.request.urlopen(request, timeout=180) as response, target.open('wb') as output:
        assert response.url.startswith('https://')
        while data := response.read(1024 * 1024):
            size += len(data)
            assert size <= maximum, 'Download too large'
            sha.update(data); output.write(data)
    if expected:
        assert size == expected['size'] and sha.hexdigest() == expected['sha256'], 'Public download mismatch: ' + target.name
    return {'size': size, 'sha256': sha.hexdigest()}


def api(method, endpoint, data=None, file=None):
    host = 'uploads.github.com' if file else 'api.github.com'
    headers = {'User-Agent': AGENT, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
               'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN']}
    stream = None
    try:
        if file:
            stream = file.open('rb'); payload = stream
            headers.update({'Content-Type': 'application/octet-stream', 'Content-Length': str(file.stat().st_size)})
        elif data is not None:
            payload = json.dumps(data).encode(); headers['Content-Type'] = 'application/json'
        else:
            payload = None
        request = urllib.request.Request('https://' + host + '/repos/' + REPOSITORY + endpoint, data=payload, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        if method == 'GET' and error.code == 404:
            return None
        raise RuntimeError(f'GitHub {method} {endpoint} failed: HTTP {error.code}') from None
    finally:
        if stream:
            stream.close()


def main():
    assert os.environ['GITHUB_REPOSITORY'] == REPOSITORY
    task = json.loads(Path('android-next-release.json').read_text())
    assert re.fullmatch(r'[0-9]{1,20}-[0-9]{1,3}', task['build'])
    assert re.fullmatch(r'[a-f0-9]{40}', task['source_sha'])
    assert re.fullmatch(r'android-next-[0-9][A-Za-z0-9.\-]*', task['tag'])
    output = Path('release-public'); output.mkdir(exist_ok=True)
    base = ORIGIN + '/android-next/artifacts/' + task['build']
    manifest_path = output / 'build-manifest.json'
    manifest_info = public_download(base + '/build-manifest.json', manifest_path, maximum=131072)
    manifest = json.loads(manifest_path.read_text())
    assert manifest['schema'] == 1 and manifest['build'] == task['build'] and manifest['source_sha'] == task['source_sha']
    assert manifest['certificate_sha256'] == PIN
    feed = manifest['feed']
    assert feed['schema'] == 1 and feed['platform'] == 'android' and feed['package_name'] == 'dev.voxel.minecraftengine.next'
    assert len(feed['versions']) == 1 and feed['launcher']['package_name'] == 'dev.voxel.minecraftengine.next.launcher'
    assert task['tag'] == 'android-next-' + feed['launcher']['version'].removesuffix('-next')
    for name in FILES:
        public_download(base + '/' + name, output / name, manifest['files'][name])
    assert json.loads((output / 'android-feed.json').read_text()) == feed
    tools = Path(os.environ['ANDROID_HOME']) / 'build-tools/35.0.0'
    for name, metadata, package in [('MinecraftEngine-Android.apk', feed['versions'][0], 'dev.voxel.minecraftengine.next'),
                                     ('MinecraftEngine-Launcher.apk', feed['launcher'], 'dev.voxel.minecraftengine.next.launcher')]:
        path = output / name
        assert metadata['url'] == base + '/' + name
        assert metadata['size'] == manifest['files'][name]['size'] and metadata['sha256'] == manifest['files'][name]['sha256']
        badging = subprocess.check_output([str(tools / 'aapt2'), 'dump', 'badging', str(path)], text=True)
        assert f"package: name='{package}' versionCode='{metadata['version_code']}' versionName='{metadata['version']}'" in badging
        signature = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(path)], text=True)
        pins = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([a-fA-F0-9]{64})$', signature, re.M)
        assert len(pins) == 1 and pins[0].lower() == PIN
        subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(path)], check=True)
    notes = ('Мобильный выпуск Mobile Next с новой подписью и отдельными пакетами. '
             'Устанавливается рядом с прежними приложениями. Миры старой игры остаются в ней; автоматического импорта нет.\n\n'
             'Для установки скачайте MinecraftEngine-Launcher.apk, затем установите игру через него. '
             'Аккаунты и друзья работают через публичный HTTPS-сервер. Следующие обновления Next доступны через лаунчер.\n\n'
             + feed['launcher']['notes'] + '\n\nИсходники сборки: PRoGG1111/minecraft-engine@' + task['source_sha'] + '\n')
    latest_before = api('GET', '/releases/latest')
    release = api('GET', '/releases/tags/' + task['tag'])
    if release is None:
        release = api('POST', '/releases', {'tag_name': task['tag'], 'name': 'Minecraft Engine Mobile Next ' + feed['launcher']['version'],
                      'body': notes, 'draft': True, 'prerelease': True, 'make_latest': 'false'})
    if release['draft']:
        for name in FILES + ['build-manifest.json']:
            for asset in release['assets']:
                if asset['name'] == name:
                    api('DELETE', '/releases/assets/' + str(asset['id']))
            api('POST', f"/releases/{release['id']}/assets?name=" + urllib.parse.quote(name), file=output / name)
        api('PATCH', '/releases/' + str(release['id']), {'draft': False, 'prerelease': True, 'make_latest': 'false'})
    # Existing published releases are immutable: verify them instead of replacing assets.
    verification = output / 'download-check'; verification.mkdir(exist_ok=True)
    for name in FILES + ['build-manifest.json']:
        info = manifest_info if name == 'build-manifest.json' else manifest['files'][name]
        public_download('https://github.com/' + REPOSITORY + '/releases/download/' + task['tag'] + '/' + name,
                        verification / name, info)
    latest_after = api('GET', '/releases/latest')
    assert (latest_before or {}).get('id') == (latest_after or {}).get('id'), 'Windows latest release changed'
    url = 'https://github.com/' + REPOSITORY + '/releases/tag/' + task['tag']
    Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('Published and verified full anonymous downloads: ' + url + '\n')
    print('VERIFIED_PUBLIC_RELEASE ' + url)


if __name__ == '__main__':
    main()
