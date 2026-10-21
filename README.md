# Robô de vídeo · Portal Sanas

A cada 30 minutos, o GitHub Actions roda `robo.py`:

1. pede ao sistema do Portal (Apps Script) os vídeos marcados como **Autorizado**;
2. baixa o vídeo do **Instagram** (Reel ou post, via `yt-dlp`). YouTube e TikTok bloqueiam servidores e ficam fora: para TikTok, suba o arquivo pelo Estúdio do painel;
3. edita no padrão Portal: tarja, logo, crédito da fonte e encerramento "Siga @portalsanas", e gera a capa 9:16 (com a área do grid 3:4 respeitada);
4. devolve vídeo e capa ao sistema, que cria o post do Reels em **Posts › Para aprovar**.

Se o download for bloqueado, o vídeo fica como **Enviar arquivo** no painel, e dá para subir o original pelo Estúdio de vídeo.

## Configuração (uma vez)

Em **Settings › Secrets and variables › Actions › New repository secret**:

- `PORTAL_URL`: URL do app da Web do Apps Script (termina em `/exec`)
- `PORTAL_CHAVE`: a chave do painel (aba Config da planilha, `CHAVE_PAINEL`)

Para rodar na hora: **Actions › Robô de vídeo › Run workflow**.

Teste local: `python robo.py teste video.mp4 pasta_saida`
