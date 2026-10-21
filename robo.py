"""Robô de vídeo do Portal Sanas.

Roda no GitHub Actions a cada 30 minutos:
1. pede ao sistema (Apps Script) a fila de vídeos autorizados;
2. baixa cada vídeo (YouTube, Instagram, TikTok... via yt-dlp, ou o link direto da API);
3. edita no padrão Portal (tarja, logo, crédito, encerramento) e gera a capa;
4. devolve vídeo + capa ao sistema, que cria o post do Reels para aprovação.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

URL = os.environ.get('PORTAL_URL', '')
CHAVE = os.environ.get('PORTAL_CHAVE', '')
AQUI = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
AZUL, ESC, TEXTO, BRANCO = (0, 83, 206), (10, 37, 80), (17, 20, 24), (255, 255, 255)
FIM = 2.5           # segundos do encerramento
LIMITE_MB = 20      # tamanho máximo do vídeo final (o Apps Script recebe até ~50 MB em base64)


def fonte(peso, tam):
    arq = {'bold': 'Poppins-Bold.ttf', 'medium': 'Poppins-Medium.ttf'}[peso]
    return ImageFont.truetype(os.path.join(AQUI, 'assets', arq), tam)


LOGO = Image.open(os.path.join(AQUI, 'assets', 'logo-branco.png')).convert('RGBA')


def logo(h):
    return LOGO.resize((round(LOGO.width * h / LOGO.height), h), Image.LANCZOS)


# ---------------------------------------------------------------- desenho
def linhas(d, txt, f, largura):
    out, atual = [], ''
    for p in str(txt).split():
        teste = (atual + ' ' + p).strip()
        if d.textlength(teste, font=f) > largura and atual:
            out.append(atual)
            atual = p
        else:
            atual = teste
    if atual:
        out.append(atual)
    return out[:4] or [' ']


def tarja(img, x, base, titulo, chamada, tam):
    """Tarja do Portal: barra azul + caixa branca com o título + rótulo azul. Devolve o topo."""
    d = ImageDraw.Draw(img)
    fb, pad, lh = fonte('bold', tam), round(tam * 0.5), round(tam * 1.16)
    ls = linhas(d, titulo, fb, W - x - 70 - pad * 2)
    bw = max(d.textlength(l, font=fb) for l in ls) + pad * 2
    bh = len(ls) * lh + pad * 1.1
    ct = round(tam * 0.5)
    fc = fonte('bold', ct)
    cw = d.textlength(chamada, font=fc) + ct * 1.4 if chamada else 0
    ch = round(ct * 1.9) if chamada else 0
    topo = base - bh - ch
    d.rectangle([x - 16, topo, x - 1, topo + bh + ch], fill=AZUL)
    d.rectangle([x, topo, x + bw, topo + bh], fill=BRANCO)
    for i, l in enumerate(ls):
        d.text((x + pad, topo + pad * 0.55 + lh * (i + 1) - lh * 0.22), l, font=fb, fill=TEXTO, anchor='ls')
    if chamada:
        d.rectangle([x, topo + bh, x + cw, topo + bh + ch], fill=AZUL)
        d.text((x + ct * 0.7, topo + bh + ch * 0.68), chamada, font=fc, fill=BRANCO, anchor='ls')
    return topo


def credito(img, x, y, txt):
    if not txt:
        return
    d = ImageDraw.Draw(img)
    f = fonte('medium', 30)
    w = d.textlength(txt, font=f) + 40
    camada = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(camada).rounded_rectangle([x, y, x + w, y + 52], radius=26, fill=ESC + (153,))
    img.alpha_composite(camada)
    ImageDraw.Draw(img).text((x + 20, y + 36), txt, font=f, fill=BRANCO, anchor='ls')


def veu(y0):
    """Degradê azul-escuro embaixo (leitura da tarja) e em cima (leitura da logo)."""
    v = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    px = v.load()
    for y in range(H):
        a = 0
        if y >= y0:
            a = round(0.85 * 255 * (y - y0) / (H - y0))
        if y < 460:
            a = max(a, round(0.55 * 255 * (1 - y / 460)))
        if a:
            for x in range(W):
                px[x, y] = ESC + (a,)
    return v


def fundo(quadro):
    """Vídeo vertical: preenche a tela. Horizontal: fundo desfocado + vídeo inteiro no centro."""
    sw, sh = quadro.size
    k = max(W / sw, H / sh)
    cheio = quadro.resize((round(sw * k), round(sh * k)), Image.LANCZOS)
    cheio = cheio.crop(((cheio.width - W) // 2, (cheio.height - H) // 2, (cheio.width - W) // 2 + W, (cheio.height - H) // 2 + H))
    if sw / sh <= 0.75:
        return cheio.convert('RGBA')
    bg = cheio.filter(ImageFilter.GaussianBlur(36)).point(lambda v: v * 0.5).convert('RGBA')
    fg = quadro.resize((W, round(sh * W / sw)), Image.LANCZOS)
    bg.paste(fg, (0, (H - fg.height) // 2 - 140))
    return bg


def capa(quadro, j):
    img = fundo(quadro)
    img.alpha_composite(veu(900))
    lg = logo(110)
    img.alpha_composite(lg, (70, 290))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([W - 270, 300, W - 70, 362], radius=31, fill=AZUL)
    d.polygon([(W - 240, 318), (W - 240, 344), (W - 218, 331)], fill=BRANCO)
    d.text((W - 204, 342), 'VÍDEO', font=fonte('bold', 30), fill=BRANCO, anchor='ls')
    tarja(img, 86, 1560, j['titulo'], j.get('chamada', ''), 70)
    credito(img, 70, 1590, j.get('credito', ''))
    return img.convert('RGB')


def camadas(j, pasta):
    """PNGs transparentes que o ffmpeg sobrepõe ao vídeo."""
    fixo = veu(1000)
    fixo.alpha_composite(logo(96), (64, 130))
    fixo.save(os.path.join(pasta, 'fixo.png'))
    t = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    tarja(t, 80, 1470, j['titulo'], j.get('chamada', ''), 56)
    t.save(os.path.join(pasta, 'tarja.png'))
    c = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    credito(c, 64, 1500, j.get('credito', ''))
    c.save(os.path.join(pasta, 'cred.png'))
    fim = Image.new('RGB', (W, H), AZUL)
    lg = logo(300)
    fim.paste(lg, ((W - lg.width) // 2, 620), lg)
    d = ImageDraw.Draw(fim)
    d.text((W / 2, 1080), 'Siga @portalsanas', font=fonte('bold', 64), fill=BRANCO, anchor='ms')
    d.text((W / 2, 1150), 'Os negócios de São José dos Campos e região', font=fonte('medium', 38), fill=BRANCO, anchor='ms')
    if j.get('credito'):
        d.text((W / 2, 1240), j['credito'], font=fonte('medium', 30), fill=(225, 233, 248), anchor='ms')
    fim.save(os.path.join(pasta, 'fim.png'))


# ---------------------------------------------------------------- vídeo
def roda(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-1500:])
    return r.stdout


def sonda(arq):
    info = json.loads(roda(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', arq]))
    v = next(s for s in info['streams'] if s['codec_type'] == 'video')
    rot = 0
    for sd in v.get('side_data_list', []) or []:
        rot = abs(int(sd.get('rotation', 0) or 0))
    w, h = int(v['width']), int(v['height'])
    if rot in (90, 270):
        w, h = h, w
    tem_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    return w, h, float(info['format']['duration']), tem_audio


def baixa(j, pasta):
    destino = os.path.join(pasta, 'origem.mp4')
    erros = []
    if j.get('mediaUrl'):
        try:
            r = requests.get(j['mediaUrl'], timeout=120)
            r.raise_for_status()
            open(destino, 'wb').write(r.content)
            return destino
        except Exception as e:  # noqa: BLE001
            erros.append('link direto: %s' % e)
    try:
        roda(['yt-dlp', '--no-playlist', '--no-progress', '-f',
              'bv*[height<=1920][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b',
              '--merge-output-format', 'mp4', '-o', destino, j['link']])
        return destino
    except Exception as e:  # noqa: BLE001
        erros.append('yt-dlp: %s' % str(e)[-400:])
    raise RuntimeError(' | '.join(erros))


def edita(j, origem, pasta):
    w, h, dur, tem_audio = sonda(origem)
    dur = min(dur, 170.0)  # Reels via API: até 3 min com o encerramento
    total = dur + FIM - 0.4
    camadas(j, pasta)
    q = os.path.join(pasta, 'quadro.png')
    roda(['ffmpeg', '-y', '-ss', str(min(dur / 3, 3)), '-i', origem, '-frames:v', '1', q])
    capa(Image.open(q).convert('RGB'), j).save(os.path.join(pasta, 'capa.jpg'), quality=92)

    if w / h <= 0.75:
        base = '[0:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1[bg]' % (W, H, W, H)
    else:
        base = ('[0:v]split[a][b];[a]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=40:2,'
                'eq=brightness=-0.25[b0];[b]scale=%d:-2[fg];[b0][fg]overlay=0:(H-h)/2-140,setsar=1[bg]') % (W, H, W, H, W)
    filtro = ';'.join([
        base,
        '[bg][1:v]overlay=0:0[v1]',
        '[2:v]format=rgba,fade=t=in:st=0.3:d=0.6:alpha=1[tj]',
        "[v1][tj]overlay=x='-120*pow(1-min(max((t-0.3)/0.6,0),1),3)':y=0[v2]",
        '[3:v]format=rgba,fade=t=in:st=0.8:d=0.4:alpha=1[cr]',
        '[v2][cr]overlay=0:0,fps=30,format=yuv420p,trim=duration=%.3f,setpts=PTS-STARTPTS[main]' % dur,
        '[4:v]fps=30,format=yuv420p,setsar=1,trim=duration=%.3f,setpts=PTS-STARTPTS[fim]' % FIM,
        '[main][fim]xfade=transition=fade:duration=0.4:offset=%.3f[v]' % (dur - 0.4),
        '[%s]atrim=0:%.3f,asetpts=PTS-STARTPTS,afade=t=out:st=%.3f:d=0.8,apad,atrim=0:%.3f[a]'
        % ('0:a' if tem_audio else '5:a', dur, max(dur - 0.8, 0), total),
    ])
    kbps = max(1500, min(6000, int(LIMITE_MB * 8 * 1024 / total) - 160))
    cmd = ['ffmpeg', '-y', '-i', origem,
           '-loop', '1', '-i', os.path.join(pasta, 'fixo.png'),
           '-loop', '1', '-i', os.path.join(pasta, 'tarja.png'),
           '-loop', '1', '-i', os.path.join(pasta, 'cred.png'),
           '-loop', '1', '-t', str(FIM), '-i', os.path.join(pasta, 'fim.png')]
    if not tem_audio:
        cmd += ['-f', 'lavfi', '-t', str(total), '-i', 'anullsrc=r=44100:cl=stereo']
    saida = os.path.join(pasta, 'reels.mp4')
    cmd += ['-filter_complex', filtro, '-map', '[v]', '-map', '[a]', '-t', '%.3f' % total,
            '-c:v', 'libx264', '-profile:v', 'high', '-preset', 'medium', '-b:v', '%dk' % kbps,
            '-maxrate', '%dk' % int(kbps * 1.5), '-bufsize', '%dk' % (kbps * 2), '-pix_fmt', 'yuv420p', '-r', '30',
            '-c:a', 'aac', '-b:a', '128k', '-ar', '44100', '-ac', '2', '-movflags', '+faststart', saida]
    roda(cmd)
    return saida, os.path.join(pasta, 'capa.jpg')


# ---------------------------------------------------------------- conversa com o sistema
def chama_sistema(dados):
    dados = dict(dados, robo=dados.get('robo', 'reels'), chave=CHAVE)
    r = requests.post(URL, data=json.dumps(dados), headers={'Content-Type': 'text/plain'}, timeout=300)
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {'ok': False, 'http': r.status_code, 'texto': r.text[:300]}


def main():
    if not URL or not CHAVE:
        sys.exit('Faltam PORTAL_URL e/ou PORTAL_CHAVE (Settings > Secrets and variables > Actions).')
    fila = requests.get(URL, params={'robo': 'fila', 'chave': CHAVE}, timeout=300).json()
    if isinstance(fila, dict):
        sys.exit('Sistema respondeu: %s' % fila)
    print('Vídeos na fila: %d' % len(fila))
    for j in fila:
        print('→', j['id'], j['link'])
        with tempfile.TemporaryDirectory() as pasta:
            try:
                origem = baixa(j, pasta)
                video, cp = edita(j, origem, pasta)
                mb = os.path.getsize(video) / 1e6
                print('  editado: %.1f MB' % mb)
                r = chama_sistema({'robo': 'reels', 'id': j['id'],
                                   'video': base64.b64encode(open(video, 'rb').read()).decode(),
                                   'capa': base64.b64encode(open(cp, 'rb').read()).decode()})
                print('  sistema:', r)
            except Exception as e:  # noqa: BLE001
                print('  ERRO:', e)
                print('  sistema:', chama_sistema({'robo': 'erro', 'id': j['id'], 'erro': str(e)[-600:]}))


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == 'teste':
        # teste local: python robo.py teste video.mp4 [pasta_saida]
        j = {'id': 'teste', 'titulo': 'Capitão Jack Sparrow é visto andando pelas ruas de SJC',
             'chamada': 'São José dos Campos', 'credito': 'Vídeo: Cabeça GG'}
        saida = sys.argv[3] if len(sys.argv) > 3 else '.'
        v, c = edita(j, sys.argv[2], saida)
        print(v, c, sonda(v))
    else:
        main()
