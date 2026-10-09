"""Narração local: pip install piper-tts; baixar pt_BR-faber-medium fora do repo.
Uso: python scripts/synthesize-film.py /caminho/pt_BR-faber-medium.onnx
O modelo não é uma dependência da API nem utiliza créditos de terceiros.
"""
import json,sys,wave
from pathlib import Path
from piper import PiperVoice,SynthesisConfig
root=Path(__file__).resolve().parents[1]
script=json.loads((root/'assets/film-script.json').read_text())
voice=PiperVoice.load(sys.argv[1])
for i,chapter in enumerate(script['chapters']):
 target=root/f'assets/audio/voice-{i}.wav'
 with wave.open(str(target),'wb') as output:
  voice.synthesize_wav(chapter['text'],output,SynthesisConfig(length_scale=.93,noise_scale=.6,noise_w_scale=.65))
 with wave.open(str(target),'rb') as audio:
  duration=audio.getnframes()/audio.getframerate()
 print(f'{i}: {duration:.2f}s; espaço {chapter["end"]-chapter["start"]}s',flush=True)
