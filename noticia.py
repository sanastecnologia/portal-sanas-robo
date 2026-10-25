"""Reels de notícia, versão 2: cenas próprias em 9:16 desenhadas quadro a quadro.

Cenas: gancho (foto + manchete) → o fato → número em destaque (quando houver) → por que importa.
O movimento da foto é uma transformação afim com interpolação bicúbica em ponto flutuante
(sem o arredondamento por pixel do zoompan, que causava o tremido). O texto entra palavra
por palavra (manchete) ou linha por linha (cenas de texto); as cenas se ligam por transições
de 0,35 s marcadas na batida da música. O edita() do robo.py põe a logo, o encerramento e o áudio.
"""
import datetime
import math
import os
import re
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

AQUI = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
AZUL, ESC, BRANCO, CLARO = (0, 83, 206), (10, 37, 80), (255, 255, 255), (225, 233, 248)
DESTAQUE = (127, 178, 255)   # números dentro do texto
TRANS = 0.35                 # duração das transições entre cenas
MIN_LARGURA = 500            # abaixo disso a foto não serve nem de fundo: o reels não sai
CHEIA_LARGURA = 1080         # foto em tela cheia só com 1080 px de largura ou mais...
CHEIA_RECORTE = 720          # ...e com o recorte 9:16 tendo pelo menos 720 px (no máx. 1,5x de ampliação)
ANOS_ANTIGA = 4              # foto com data (EXIF ou ano no link) mais velha que isso: não sai


class FotoRuim(Exception):
    """Foto pequena demais ou antiga: o reels de notícia não é gerado."""


def fonte(peso, tam):
    arq = {'bold': 'Poppins-Bold.ttf', 'medium': 'Poppins-Medium.ttf'}[peso]
    return ImageFont.truetype(os.path.join(AQUI, 'assets', arq), tam)


# ---------------------------------------------------------------- curvas de movimento
def lim(x):
    return max(0.0, min(1.0, x))


def suave(x):            # ease-in-out (cosseno)
    x = lim(x)
    return 0.5 - 0.5 * math.cos(math.pi * x)


def sai(x):              # ease-out cúbico
    x = lim(x)
    return 1 - (1 - x) ** 3


def volta(x):            # ease-out com um leve passo além (pop do número)
    x = lim(x)
    c = 1.4
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


# ---------------------------------------------------------------- foto
def avalia_foto(img, info):
    """Decide como a foto entra: 'cheia', 'cartao' (foto inteira sobre fundo desfocado) ou 'fundo'.
    Levanta FotoRuim se for pequena demais ou claramente antiga."""
    w, h = img.size
    if w < MIN_LARGURA:
        raise FotoRuim('foto pequena demais (%dx%d)' % (w, h))
    ano = None
    try:
        ex = img.getexif()
        bruto = ex.get_ifd(0x8769).get(36867) or ex.get(306)   # DateTimeOriginal ou DateTime
        if bruto:
            ano = int(str(bruto)[:4])
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r'/((?:19|20)\d{2})/(?:0[1-9]|1[0-2])/', str(info.get('origem', '')))
    if m:
        ano = min(ano or 9999, int(m.group(1)))
    if ano and datetime.date.today().year - ano > ANOS_ANTIGA:
        raise FotoRuim('foto antiga (%d)' % ano)
    if w >= CHEIA_LARGURA and min(w, h * 9 / 16) >= CHEIA_RECORTE:
        return 'cheia'
    if w >= CHEIA_LARGURA:
        return 'cartao'
    return 'fundo'


def preenche(img, fw, fh, foco=None):
    """Recorta a foto para fw x fh (cobrindo tudo), centrando no foco (x, y em 0..1). Redução com Lanczos."""
    fx, fy = (foco or {}).get('x', 0.5), (foco or {}).get('y', 0.45)
    k = max(fw / img.width, fh / img.height)
    bw, bh = fw / k, fh / k
    x0 = min(max(fx * img.width - bw / 2, 0), img.width - bw)
    y0 = min(max(fy * img.height - bh / 2, 0), img.height - bh)
    return img.resize((fw, fh), Image.LANCZOS, box=(x0, y0, x0 + bw, y0 + bh))


def kenburns(src, fw, fh, z0, z1, dx, dy, p):
    """Quadro do movimento (p em 0..1): zoom de z0 a z1 sobre src (mesma proporção da saída) e
    deslocamento até (dx, dy) px da saída. Posição e escala em ponto flutuante: nada de tremido."""
    e = suave(p)
    z = z0 + (z1 - z0) * e
    s = src.width / fw / z
    cx = src.width / 2 + dx * e * s
    cy = src.height / 2 + dy * e * s
    return src.transform((fw, fh), Image.AFFINE, (s, 0, cx - s * fw / 2, 0, s, cy - s * fh / 2), Image.BICUBIC)


def borrado(img, escuro):
    b = preenche(img, W // 4, H // 4).filter(ImageFilter.GaussianBlur(10))
    b = b.resize((int(W * 1.12), int(H * 1.12)), Image.BICUBIC)
    return Image.eval(b, lambda v: int(v * escuro))


def degrade(y0, y1, a0, a1, cor=ESC):
    """Camada RGBA com degradê vertical de alpha a0 (em y0) a a1 (em y1)."""
    col = Image.new('L', (1, H), 0)
    px = col.load()
    for y in range(H):
        if y0 <= y <= y1:
            px[0, y] = int(255 * (a0 + (a1 - a0) * (y - y0) / max(y1 - y0, 1)))
        elif y > y1 and y1 > y0:
            px[0, y] = int(255 * a1)
    camada = Image.new('RGBA', (W, H), cor + (0,))
    camada.putalpha(col.resize((W, H)))
    return camada


# ---------------------------------------------------------------- texto
def quebra(d, txt, f, largura, maximo):
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
    if len(out) > maximo:
        out = out[:maximo]
        out[-1] = out[-1].rstrip('.,;:') + '…'
    return out


_rasc = ImageDraw.Draw(Image.new('RGB', (8, 8)))


def cabe(txt, peso, tams, largura, maximo):
    """Maior fonte da lista em que o texto cabe sem cortar."""
    for t in tams:
        f = fonte(peso, t)
        ls = quebra(_rasc, txt, f, largura, 99)
        if len(ls) <= maximo:
            return f, ls
    f = fonte(peso, tams[-1])
    return f, quebra(_rasc, txt, f, largura, maximo)


def pilula(cam, x, y, txt, fundo_cor, cor, tam=34, alpha=1.0, centro=False):
    d = ImageDraw.Draw(cam)
    f = fonte('bold', tam)
    w = d.textlength(txt, font=f) + tam * 1.3
    h = tam * 1.75
    if centro:
        x = x - w / 2
    a = int(255 * alpha)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=fundo_cor + (a,))
    d.text((x + tam * 0.65, y + h * 0.69), txt, font=f, fill=cor + (a,), anchor='ls')
    return h


UNIDADES = {'r$', 'us$', 'mil', 'milhão', 'milhões', 'bi', 'bilhão', 'bilhões', 'tri', '%', 'vagas', 'reais'}


def destaques(ls):
    """Quais palavras pintar: números (menos anos) e o que vem colado neles (R$, US$, mil, bi, %...)."""
    ps = [p for l in ls for p in l.split(' ')]
    num = [bool(re.search(r'\d', p)) and not re.fullmatch(r'(19|20)\d{2}[.,;:]?', p) for p in ps]
    out = list(num)
    for i, p in enumerate(ps):
        base = p.lower().strip('.,;:')
        if base in UNIDADES and ((i > 0 and num[i - 1]) or (i + 1 < len(ps) and num[i + 1])):
            out[i] = True
    return iter(out)


def palavras(cam, ls, f, x, y, lh, t, ini, passo, cor=BRANCO, centro=False):
    """Manchete entrando palavra por palavra: cada uma sobe 28 px e aparece em 0,35 s."""
    d = ImageDraw.Draw(cam)
    k, pinta = 0, destaques(ls)
    for i, linha in enumerate(ls):
        larg = d.textlength(linha, font=f)
        cx = x - larg / 2 if centro else x
        for p in linha.split(' '):
            q = sai((t - ini - k * passo) / 0.35)
            c = DESTAQUE if next(pinta) else cor
            if q > 0:
                d.text((cx, y + i * lh + 28 * (1 - q)), p, font=f, fill=c + (int(255 * q),), anchor='ls')
            cx += d.textlength(p + ' ', font=f)
            k += 1
    return ini + k * passo + 0.35


def linhas_entrando(cam, ls, f, x, y, lh, t, ini, passo, cor=BRANCO):
    """Texto entrando linha por linha: cada linha desliza 40 px da esquerda e aparece em 0,45 s."""
    d = ImageDraw.Draw(cam)
    pinta = destaques(ls)
    for i, linha in enumerate(ls):
        q = sai((t - ini - i * passo) / 0.45)
        marcas = [next(pinta) for _ in linha.split(' ')]
        if q <= 0:
            continue
        cx = x - 40 * (1 - q)
        for p, m in zip(linha.split(' '), marcas):
            c = DESTAQUE if m else cor
            d.text((cx, y + i * lh), p, font=f, fill=c + (int(255 * q),), anchor='ls')
            cx += d.textlength(p + ' ', font=f)
    return ini + len(ls) * passo + 0.45


# ---------------------------------------------------------------- cenas
class Gancho:
    """Foto com movimento suave + rótulo + manchete palavra por palavra + fonte."""

    def __init__(self, foto, modo, j, dur):
        self.modo, self.j, self.dur = modo, j, dur
        foco = j.get('foco')
        if modo == 'cheia':
            self.src = preenche(foto, W, H, foco)
        else:
            self.bg = borrado(foto, 0.42 if modo == 'cartao' else 0.5)
        if modo == 'cartao':
            cw = W - 120
            ch = min(int(cw * foto.height / foto.width), 760)
            self.card = [60, 0, cw, ch]
            self.src = preenche(foto, cw, ch, foco)
            m = Image.new('L', (cw, ch), 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=28, fill=255)
            self.mascara = m
        self.f, self.ls = cabe(j['titulo'], 'bold', [86, 78, 70], W - 170, 4)
        self.lh = int(self.f.size * 1.14)
        bloco = len(self.ls) * self.lh
        if modo == 'cartao':
            # foto + rótulo + manchete + fonte centrados na altura útil da tela
            grupo = self.card[3] + 150 + bloco + 50
            self.card[1] = max(300, int(960 - grupo / 2))
            self.ty = self.card[1] + self.card[3] + 150 + self.lh
        elif modo == 'cheia':
            self.ty = 1545 - bloco + self.lh
        else:
            self.ty = int(980 - bloco / 2 + self.lh)
        self.sombra = degrade(760, 1700, 0, 0.93) if modo == 'cheia' else None
        self.topo = degrade(0, 420, 0.55, 0) if modo == 'cheia' else None

    def quadro(self, t):
        p = t / self.dur
        if self.modo == 'cheia':
            img = kenburns(self.src, W, H, 1.0, 1.10, 0, -60, p).convert('RGBA')
            img.alpha_composite(self.sombra)
            img.alpha_composite(self.topo)
        else:
            img = kenburns(self.bg, W, H, 1.0, 1.06, 0, 0, p).convert('RGBA')
        if self.modo == 'cartao':
            x, y, cw, ch = self.card
            q = sai(t / 0.6)
            foto = kenburns(self.src, cw, ch, 1.0, 1.07, 0, 0, p)
            sombra = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(sombra).rounded_rectangle([x + 6, y + 18, x + cw + 6, y + ch + 18], radius=30, fill=(0, 0, 0, int(110 * q)))
            img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(18)))
            img.paste(foto, (x, int(y + 40 * (1 - q))), Image.eval(self.mascara, lambda v: int(v * q)))
        cam = Image.new('RGBA', (W, H), (255, 255, 255, 0))
        x = 84 if self.modo != 'fundo' else W / 2
        centro = self.modo == 'fundo'
        if self.j.get('chamada'):
            a = sai((t - 0.1) / 0.4)
            pilula(cam, x + (0 if centro else -30 * (1 - a)), self.ty - self.lh - 82, self.j['chamada'].upper(), AZUL, BRANCO,
                   alpha=a, centro=centro)
        if not centro:
            fim = 0.3 + len(self.j['titulo'].split()) * 0.07 + 0.35
            barra = sai((t - 0.25) / (fim - 0.25))
            alto = (len(self.ls) * self.lh - self.lh * 0.25) * barra
            ImageDraw.Draw(cam).rectangle([58, self.ty - self.lh * 0.78, 68, self.ty - self.lh * 0.78 + alto], fill=AZUL + (255,))
        palavras(cam, self.ls, self.f, x, self.ty, self.lh, t, 0.3, 0.07, centro=centro)
        if self.j.get('credito'):
            a = sai((t - 1.0) / 0.5)
            yc = self.ty + (len(self.ls) - 1) * self.lh + 62
            fc = fonte('medium', 28)
            for i, l in enumerate(quebra(_rasc, self.j['credito'], fc, W - 170, 2)):
                ImageDraw.Draw(cam).text((x, yc + i * 38), l, font=fc, fill=CLARO + (int(220 * a),), anchor='ms' if centro else 'ls')
        img.alpha_composite(cam)
        return img.convert('RGB')


class Texto:
    """Rótulo + texto entrando linha por linha, sobre a foto borrada (o fato) ou o degradê azul (por que importa)."""

    def __init__(self, foto, rotulo, texto, dur, estilo):
        self.rotulo, self.dur, self.estilo = rotulo, dur, estilo
        if estilo == 'fato':
            self.bg = borrado(foto, 0.55)
            veu = Image.new('RGBA', self.bg.size, ESC + (190,))
            self.bg = Image.alpha_composite(self.bg.convert('RGBA'), veu).convert('RGB')
        else:
            g = Image.new('RGB', (1, 2))
            g.putpixel((0, 0), AZUL)
            g.putpixel((0, 1), ESC)
            self.bg = g.resize((int(W * 1.12), int(H * 1.12)), Image.BICUBIC)
        self.f, self.ls = cabe(texto, 'bold', [66, 60, 54, 50], W - 180, 8)
        self.lh = int(self.f.size * 1.32)
        bloco = 120 + len(self.ls) * self.lh
        self.y0 = int(1000 - bloco / 2)

    def quadro(self, t):
        img = kenburns(self.bg, W, H, 1.0, 1.05, 0, 0, t / self.dur).convert('RGBA')
        cam = Image.new('RGBA', (W, H), (255, 255, 255, 0))
        d = ImageDraw.Draw(cam)
        a = sai((t - 0.05) / 0.4)
        if self.estilo == 'fato':
            pilula(cam, 90 - 30 * (1 - a), self.y0, self.rotulo, AZUL, BRANCO, tam=36, alpha=a)
        else:
            pilula(cam, 90 - 30 * (1 - a), self.y0, self.rotulo, BRANCO, AZUL, tam=36, alpha=a)
        ini = 0.3
        fim = linhas_entrando(cam, self.ls, self.f, 90, self.y0 + 120 + self.lh * 0.8, self.lh, t, ini, 0.2)
        barra = sai((t - ini) / (fim - ini))
        d.rectangle([90, self.y0 + 120 + len(self.ls) * self.lh + 10, 90 + 220 * barra, self.y0 + 120 + len(self.ls) * self.lh + 18],
                    fill=(BRANCO if self.estilo != 'fato' else AZUL) + (255,))
        img.alpha_composite(cam)
        return img.convert('RGB')


class Numero:
    """Número grande: conta de 0 até o valor (inteiros) ou entra com um pulo; o rótulo vem depois."""

    def __init__(self, numero, rotulo, dur):
        self.num, self.rotulo, self.dur = str(numero).strip(), str(rotulo or '').strip(), dur
        g = Image.new('RGB', (1, 2))
        g.putpixel((0, 0), (12, 98, 230))
        g.putpixel((0, 1), AZUL)
        self.bg = g.resize((W, H), Image.BICUBIC)
        self.inteiro = re.fullmatch(r'\d{1,3}(\.\d{3})*|\d{1,6}', self.num)
        larg = _rasc.textlength(self.num, font=fonte('bold', 100)) / 100
        self.f = fonte('bold', int(min(300, (W - 160) / max(larg, 0.1))))
        self.fr, self.lr = cabe(self.rotulo, 'bold', [64, 56, 48], W - 200, 3)

    def quadro(self, t):
        img = self.bg.copy().convert('RGBA')
        cam = Image.new('RGBA', (W, H), (255, 255, 255, 0))
        d = ImageDraw.Draw(cam)
        if self.inteiro:
            alvo = int(self.num.replace('.', ''))
            v = int(round(alvo * sai(t / 0.9)))
            txt = '{:,}'.format(v).replace(',', '.') if '.' in self.num or alvo >= 10000 else str(v)
            esc = 0.9 + 0.1 * sai(t / 0.4)
        else:
            txt, esc = self.num, max(volta(t / 0.5), 0.01)
        a = sai(t / 0.25)
        f = fonte('bold', max(int(self.f.size * esc), 10))
        d.text((W / 2, 960), txt, font=f, fill=BRANCO + (int(255 * a),), anchor='ms')
        ar = sai((t - 0.55) / 0.4)
        for i, l in enumerate(self.lr):
            d.text((W / 2, 1060 + i * self.fr.size * 1.2 + 24 * (1 - ar)), l, font=self.fr, fill=CLARO + (int(255 * ar),), anchor='ms')
        img.alpha_composite(cam)
        return img.convert('RGB')


# ---------------------------------------------------------------- montagem
def transicao(a, b, p, tipo):
    e = suave(p)
    if tipo == 'fade':
        return Image.blend(a, b, e)
    # deslizar para cima: a sai pelo topo, b entra por baixo
    out = Image.new('RGB', (W, H))
    dy = e * H
    out.paste(a, (0, int(round(-dy))))
    out.paste(b, (0, int(round(H - dy))))
    return out


def roteiro(j, batida):
    """Duração de cada cena, sempre em número inteiro de batidas (as transições caem na batida)."""
    b = batida if batida >= 0.38 else batida * 2      # música rápida: corta a cada 2 batidas
    q = lambda s: max(1, round(s / b)) * b            # noqa: E731
    fato_s = 3.6 + min(len(j.get('fato', '').split()), 40) * 0.035
    imp_s = 3.6 + min(len(j.get('importa', '').split()), 40) * 0.035
    cenas = [('gancho', q(3.4 + min(len(j['titulo'].split()), 12) * 0.05))]
    if j.get('fato'):
        cenas.append(('fato', q(fato_s)))
    if j.get('numero'):
        cenas.append(('numero', q(2.4)))
    if j.get('importa'):
        cenas.append(('importa', q(imp_s)))
    return cenas


def duracao(cenas):
    return sum(d for _, d in cenas) - TRANS * (len(cenas) - 1)


def monta(j, foto_arq, saida, batida=0.5, fim=2.5, total_min=12.0, total_max=18.0):
    """Gera o vídeo-base (sem áudio, sem logo) e a capa. Devolve (duração, capa PIL)."""
    foto = ImageOps.exif_transpose(Image.open(foto_arq)).convert('RGB')
    modo = avalia_foto(foto, j)
    cenas = roteiro(j, batida)
    # cabe em 12–18 s contando o encerramento (que entra com 0,4 s de transição)
    while duracao(cenas) + fim - 0.4 > total_max and any(d > 2 * batida for _, d in cenas):
        i = max(range(len(cenas)), key=lambda k: cenas[k][1])
        cenas[i] = (cenas[i][0], cenas[i][1] - batida)
    while duracao(cenas) + fim - 0.4 < total_min:
        i = min(range(len(cenas)), key=lambda k: cenas[k][1])
        cenas[i] = (cenas[i][0], cenas[i][1] + batida)
    obj = []
    for nome, d in cenas:
        if nome == 'gancho':
            obj.append(Gancho(foto, modo, j, d))
        elif nome == 'fato':
            obj.append(Texto(foto, j.get('rotuloFato') or 'O FATO', j['fato'], d, 'fato'))
        elif nome == 'numero':
            obj.append(Numero(j['numero'], j.get('rotuloNumero', ''), d))
        else:
            obj.append(Texto(foto, j.get('rotuloImporta') or 'POR QUE IMPORTA', j['importa'], d, 'importa'))
    tipos = ['deslizar', 'fade', 'deslizar', 'fade']
    inicios, t0 = [], 0.0
    for _, d in cenas:
        inicios.append(t0)
        t0 += d - TRANS
    total = duracao(cenas)
    n = int(round(total * FPS))
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H),
                           '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p',
                           '-r', str(FPS), '-an', saida], stdin=subprocess.PIPE)
    try:
        for k in range(n):
            t = k / FPS
            i = max(x for x in range(len(obj)) if inicios[x] <= t + 1e-6)
            fr = obj[i].quadro(t - inicios[i])
            if i > 0 and t - inicios[i] < TRANS:
                prev = obj[i - 1].quadro(t - inicios[i - 1])
                fr = transicao(prev, fr, (t - inicios[i]) / TRANS, tipos[(i - 1) % len(tipos)])
            ff.stdin.write(fr.tobytes())
    finally:
        ff.stdin.close()
        ff.wait()
    if ff.returncode:
        raise RuntimeError('ffmpeg falhou ao montar as cenas')
    capa = obj[0].quadro(min(cenas[0][1] - 0.05, 3.0))
    return total, capa, modo, cenas
