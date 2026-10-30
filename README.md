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
| `effects/` | Os 10 efeitos (NumPy/SciPy, vetorizados por bloco) |
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
.venv\Scripts\python -m pytest tests -q      :: 70 testes
build.bat                                     :: testes + ícone + PyInstaller → dist\etioboard\
```

## Dicas de latência

- Use a API **Windows WASAPI** e buffer de 256 amostras, em "Equilibrada". Se ouvir estalos, use 512 ou "Segura".
- MME/DirectSound têm latência alta (mais de 100 ms) por natureza. WDM-KS tem latência baixa, mas muitos drivers
  não o suportam.
- O microfone pode vir de outra API (por exemplo, WDM-KS) mesmo com as saídas em WASAPI.
