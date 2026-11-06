# Robô de vídeo · Portal Sanas

A cada 30 minutos, o GitHub Actions roda `robo.py`:

1. pede ao sistema do Portal (Apps Script) os vídeos marcados como **Autorizado**;
2. baixa o vídeo do **Instagram** (Reel ou post, via `yt-dlp`). YouTube e TikTok bloqueiam servidores e ficam fora: para TikTok, suba o arquivo pelo Estúdio do painel;
3. edita no padrão Portal: tarja, logo, crédito da fonte e encerramento "Siga @portalsanas", e gera a capa 9:16 (com a área do grid 3:4 respeitada);
4. devolve vídeo e capa ao sistema, que cria o post do Reels em **Posts › Para aprovar**.

## Reels de notícia (versão 2)

As notícias mais fortes (nota do radar ≥ 3) viram um Reels de 12 a 18 s com cenas próprias em 9:16, desenhadas em `noticia.py`:
gancho (foto com movimento suave + manchete palavra por palavra) → o fato → número em destaque (quando houver) → por que importa → encerramento.

- Foto com 1080 px ou mais (e recorte 9:16 de pelo menos 720 px): tela cheia. Larga mas baixa: foto inteira num cartão sobre o fundo desfocado. Menor que 1080 px: só fundo desfocado e escurecido. Menor que 500 px ou com data de mais de 4 anos: o reels não é gerado.
- O servidor só manda notícias para o robô com `REELS_NOTICIA_V2 = sim` na Config.
- Teste local: `python robo.py noticia exemplo.json pasta_saida` (o JSON tem os campos que o `cenasNoticia_` do sistema manda).

## Entrevista gravada

No painel: **+ Adicionar › Entrevista gravada**. O vídeo sobe direto para o Drive e entra na fila como **Autorizado** (com a confirmação de autorização de imagem).
O robô baixa do Drive, transcreve com `faster-whisper` (modelo `small`, instalado só quando há entrevista na fila), manda a transcrição ao sistema,
que escolhe o trecho de 30 a 60 s (ou usa o vídeo inteiro / o trecho que o Pedro marcou) e escreve manchete e legenda. O robô corta, aplica o modelo
(tarja com a manchete, rótulo azul com o nome, pílula com cargo · empresa, logo e encerramento) e o Reels vai para **Para aprovar**, com o @ do entrevistado como colaborador.
A transcrição completa fica no Drive (pasta dos posts) para matéria e outros cortes.

Teste local: `python robo.py entrevista video.mp4 pasta_saida [inicio fim]`

## Música

Faixas livres de direitos em `assets/musica/` (mp3, m4a, wav). O robô sorteia uma por vídeo, em volume baixo, só em vídeo sem áudio próprio.
As cenas da notícia cortam na batida: o bpm sai do nome do arquivo (`faixa_120bpm.mp3`) ou é medido sozinho.

Se o download for bloqueado, o vídeo fica como **Enviar arquivo** no painel, e dá para subir o original pelo Estúdio de vídeo.

## Configuração (uma vez)

Em **Settings › Secrets and variables › Actions › New repository secret**:

- `PORTAL_URL`: URL do app da Web do Apps Script (termina em `/exec`)
- `PORTAL_CHAVE`: a chave do painel (aba Config da planilha, `CHAVE_PAINEL`)

Para rodar na hora: **Actions › Robô de vídeo › Run workflow**.

Teste local: `python robo.py teste video.mp4 pasta_saida`
