# etioboard

Modificador de voz em tempo real e soundboard para Windows, em Python + PySide6 (app desktop nativo).

```
Microfone físico → Captura → Efeitos de voz → Mixer (+ Soundboard) → Saída virtual (VB-CABLE) → Discord / jogos
                                                               └──→ Monitor (seus fones)
```

## Executar

**Executável:** `dist\etioboard\etioboard.exe` (gerado por `build.bat`).

**A partir do código-fonte** (Python 3.12+):

```bat
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py            :: --minimized inicia na bandeja
```

## Usar como microfone no Discord/jogos

O Windows só mostra como microfone os dispositivos criados por um **driver de áudio**. Nenhum app comum consegue
criar um sozinho, nem colocar som "dentro" do microfone físico (injetar áudio no processo do Discord ou do jogo é
detectado por anti-cheats). Por isso o etioboard usa o VB-CABLE, um cabo virtual gratuito, e cuida da instalação:

1. Em **Configurações**, clique em **Instalar VB-CABLE**. Na primeira execução, o app também oferece isso.
   O instalador oficial é baixado do site da VB-Audio, e a assinatura digital é conferida antes de abri-lo.
2. Confirme a permissão do Windows (UAC) e clique em **Install Driver**.
3. O etioboard detecta o cabo e passa a enviar o áudio para ele automaticamente.
4. No Discord ou no jogo, escolha **CABLE Output** como microfone.

O app também detecta VB-CABLE A/B, Hi-Fi Cable, Voicemeeter e Virtual Audio Cable. Sem cabo virtual, o app
continua funcionando, mas só toca no monitor.

**Migração do nome antigo:** os dados de `%APPDATA%\VoiceStudio` são copiados para `%APPDATA%\etioboard` na
primeira execução. A pasta antiga fica intacta como backup.

## Funcionalidades

- **Voice changer** com 10 efeitos combináveis, cada um com interruptor e controles próprios: Pitch Shift,
  Formant Shift, Reverb, Echo/Delay, Distortion, Robot Voice, Chorus, Equalizer (5 bandas), Noise Gate e
  Compressor. Ligar ou desligar um efeito faz um crossfade de 10 ms, sem estalos e sem interromper o áudio.
- **Presets**: 8 incluídos (Normal, Deep, High, Radio, Robot, Demon, Alien, Telephone). Dá para criar, editar,
  duplicar, renomear, excluir, reordenar, definir o padrão, atribuir um atalho a cada preset e restaurar os
  originais.
- **Soundboard**: grade responsiva com nome, ícone (emoji), cor, atalho e progresso de reprodução. Também permite:
  - adicionar sons pelo botão ou arrastando arquivos do Explorer (WAV/MP3/OGG/FLAC);
  - remover, renomear e substituir o arquivo;
  - ouvir uma prévia só no monitor;
  - ajustar volume e velocidade individuais;
  - tocar em loop, parar um som ou parar todos;
  - favoritar e pesquisar;
  - arrastar e soltar para reordenar ou mover entre categorias.
- **Categorias**: criar, editar, excluir (mantendo ou excluindo os sons) e reordenar.
- **Mixer**: volumes de microfone, voz processada, soundboard, monitor e saída geral, com medidores. O monitor
  pode tocar a voz e/ou o soundboard. Vários sons podem tocar ao mesmo tempo (até 32).
- **Atalhos globais** (funcionam com o app minimizado): sons, presets, mutar, ligar/desligar a voz, próximo e
  anterior preset, parar tudo. Conflitos são detectados entre as funções do app e com outros programas.
- **Sistema**: bandeja do sistema, iniciar com o Windows, iniciar minimizado, instância única, tema escuro/claro
  e cor de destaque.
- **Persistência**: SQLite em `%APPDATA%\etioboard\etioboard.db`. Os sons são copiados para
  `%APPDATA%\etioboard\sounds` e os logs ficam em `%APPDATA%\etioboard\logs`. As configurações podem ser
  exportadas e importadas em JSON.

## Auto-Tune Studio

Correção de afinação em tempo real, integrada à cadeia de voz:

```
Microfone → Noise Gate → Auto-Tune → Pitch/Formant → EQ/Compressor → efeitos → Mixer → Saída virtual
```

A ordem é configurável no Voice Changer, pelo botão de ordem de processamento.

- **Tempo real**: corrige para a nota mais próxima da tonalidade e da escala escolhidas. São 12 tonalidades e 8
  escalas: Chromatic, Major, Minor, Harmonic/Melodic Minor, Pentatonic Major/Minor e Blues. A tonalidade também
  pode ser detectada cantando por cerca de 8 s.
- **Controles**: Correction Amount, Retune Speed, Humanize (preserva o vibrato), Flex Tune, Formant Preservation
  e Reference Pitch (A4).
- **Song Mode**: importe uma música ou instrumental (WAV/MP3/OGG/FLAC). Em segundo plano, num processo separado,
  o app identifica BPM e batidas, tonalidade e mudanças de tonalidade, escala, acordes por trecho (com as notas do
  acorde e da tonalidade), estrutura (seções) e uma melodia de referência estimada.
  - **Sincronia**: a correção acompanha a posição da reprodução, por timestamp e com compensação da latência dos
    dispositivos, nos modos **Scale**, **Chord** (prioriza notas do acorde) e **Melody** (segue a melodia de
    referência).
  - **Edição**: no piano roll você corrige a tonalidade, os acordes e as notas de referência, ou importa um MIDI.
- **Separação**: a música toca só no monitor. Enviá-la ao microfone virtual é opcional (há uma caixa de seleção
  no Song Mode e no Mixer).
- **Presets**: Natural Correction, Light, Hard, Robotic, Pop, Trap e R&B Vocal, além dos seus. Um preset pode
  ser vinculado a uma música.

**Algoritmos:**

- **Detecção de F0**: YIN vetorizado por FFT, cerca de 0,05 ms por bloco. Não usei pYIN/CREPE: o pYIN só ajuda
  na análise offline, e o CREPE exige uma rede neural pesada demais para tempo real.
- **Correção**: TD-PSOLA síncrono ao período. A reconstrução é exata com razão 1, as formantes são preservadas,
  e a latência é de cerca de 27 ms.
- **Análise**: transcrição aproximada por NMF com dicionário harmônico (croma sem harmônicos e croma do baixo).
  Sobre ela rodam perfis de Krumhansl-Kessler com Viterbi (tonalidade/modulações), templates de acordes com
  Viterbi, rastreamento de batidas por programação dinâmica, novidade na matriz de auto-similaridade (seções) e
  saliência harmônica com Viterbi (melodia).

## Arquitetura

| Módulo | Responsabilidade |
|---|---|
| `audio/engine.py` | Streams PortAudio, thread de DSP e supervisor (reconexão automática) |
| `audio/device_manager.py` | Enumeração de dispositivos e detecção de cabo virtual |
| `audio/voice_processor.py` | Ganho do microfone, mute e cadeia de efeitos |
| `audio/soundboard_player.py` | Reprodução polifônica (loop, velocidade, fade) |
| `audio/audio_mixer.py` | Mixagem da saída virtual e do monitor, com limitador suave |
| `audio/audio_loader.py` | Decodificação (libsndfile), reamostragem e cache LRU assíncrono |
| `audio/ring_buffer.py` | Buffers entre os callbacks e o DSP |
| `effects/` | Os 10 efeitos (NumPy/SciPy, vetorizados por bloco) e a cadeia com ordem configurável |
| `autotune/` | YIN, TD-PSOLA, corretor, teoria musical, mapa da música, análise, MIDI e persistência |
| `audio/song_player.py` | Reprodução da música do Song Mode (posição com precisão de amostra) |
| `soundboard/library.py` | Snippets e categorias (SQLite + pasta de arquivos) |
| `presets/` | Presets incluídos e CRUD |
| `hotkeys/` | `RegisterHotKey` do Win32 numa thread com laço de mensagens próprio |
| `settings/`, `database/` | Preferências (valores JSON no SQLite) e schema |
| `core/app_controller.py` | Ponte entre o backend e a interface (sinais Qt) |
| `ui/` | Janela, páginas, widgets, tema (QSS) e ícones vetoriais |

**Decisões de tempo real:**

- **Callbacks leves.** Os callbacks do PortAudio só copiam memória.
- **DSP fora da interface.** Todo o processamento roda numa thread de DSP separada.
- **Relógio do DSP.** A thread de DSP é sincronizada pelo microfone; sem microfone, pelo consumo da saída.
- **Diferenças de clock.** A diferença entre dispositivos (microfone e saída podem ser hardwares diferentes) é
  compensada: o buffer cresce depois de um underrun e o excesso é descartado.
- **Pitch shift de baixa latência.** É granular, com alinhamento por correlação (estilo SOLA). O tom fica exato
  e o envelope não oscila. A latência média é de cerca de 12 ms.
- **Formant shift.** Usa STFT com envelope cepstral (cerca de 16 ms, só quando ativo).
- **Custo.** A cadeia completa, com os 10 efeitos ligados, usa cerca de 0,5 ms por bloco de 5,3 ms (256
  amostras a 48 kHz).
- **Troca de dispositivos sem reiniciar o app.** O supervisor detecta um dispositivo desconectado ou travado e
  reabre os streams sozinho.

## Testes e build

```bat
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest tests -q      :: testes
build.bat                                     :: testes + ícone + PyInstaller → dist\etioboard\
```

## Atualizações

O app procura novas versões nas [releases do GitHub](https://github.com/EchsDee/etioboard/releases) ao iniciar
(no máximo a cada 6 h) ou em **Configurações → Atualizações**. Ao instalar, ele baixa o zip da release, confere
o SHA-256, fecha, troca os arquivos da pasta do programa e abre de novo. Se algo falhar, a versão anterior é
restaurada. Sons, presets e configurações ficam em `%APPDATA%\etioboard` e não são tocados. O registro fica em
`%APPDATA%\etioboard\logs\update.log`.

Para publicar uma versão:

1. Aumente `APP_VERSION` em `utils/paths.py`, faça commit e push.
2. Rode `release.bat "Notas da versão"`: gera o build, o zip `etioboard-<versão>-win64.zip` com o `.sha256` e
   cria a release `v<versão>` com o `gh`.

## Dicas de latência

- Use a API **Windows WASAPI** e buffer de 256 amostras, em "Equilibrada". Se ouvir estalos, use 512 ou "Segura".
- MME/DirectSound têm latência alta (mais de 100 ms) por natureza. WDM-KS tem latência baixa, mas muitos drivers
  não o suportam.
- O microfone pode vir de outra API (por exemplo, WDM-KS) mesmo com as saídas em WASAPI.
