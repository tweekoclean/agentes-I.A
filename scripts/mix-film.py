"""Trilha original, efeitos e narração: numpy/scipy + ffmpeg; sem samples externos."""
import json,subprocess,tempfile
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
root=Path(__file__).resolve().parents[1]
script=json.loads((root/'assets/film-script.json').read_text())
rate=48000;duration=script['duration'];n=rate*duration
t=np.arange(n)/rate
music=np.zeros((n,2));voice=np.zeros(n);effects=np.zeros((n,2))
rng=np.random.default_rng(42)
def add(track,signal,start,pan=0):
 a=int(start*rate);b=min(n,a+len(signal));signal=signal[:b-a]
 if b<=a:return
 if track.ndim==1:track[a:b]+=signal
 else:track[a:b,0]+=signal*np.sqrt((1-pan)/2);track[a:b,1]+=signal*np.sqrt((1+pan)/2)
def note(hz,length,amplitude,kind='bell'):
 x=np.arange(int(rate*length))/rate
 if kind=='pad':
  env=np.minimum(x/.4,1)*np.minimum((length-x)/.6,1)
  return amplitude*env*(np.sin(2*np.pi*hz*x)+.2*np.sin(2*np.pi*hz*2*x))
 return amplitude*(1-np.exp(-x*80))*np.exp(-x*3.3)*(np.sin(2*np.pi*hz*x)+.32*np.sin(2*np.pi*hz*2*x)*np.exp(-x*6))
# Ré maior / si menor / sol maior / lá maior, cama suave e arpejo espaçado.
chords=[(146.83,185,220),(123.47,146.83,185),(98,123.47,146.83),(110,138.59,164.81)]
beat=60/90
for bar,start in enumerate(np.arange(0,duration,beat*4)):
 chord=chords[(bar//2)%4]
 for j,hz in enumerate(chord):add(music,note(hz,beat*4+.3,.018,'pad'),start,(-.4,0,.4)[j])
 for k in range(8):add(music,note(chord[k%3]*2,1.3,.026),start+k*beat/2,(-.25 if k%2 else .25))
 for k in (0,2):
  x=np.arange(int(rate*.16))/rate;hit=.022*np.sin(2*np.pi*(65*x-22*x*x))*np.exp(-x*26)
  add(music,hit,start+k*beat)
for i,c in enumerate(script['chapters']):
 source,data=wavfile.read(root/f'assets/audio/voice-{i}.wav');data=data.astype(float)/32768
 data=resample_poly(data,rate,source);data=data*.66/max(np.max(np.abs(data)),.001)
 # Respiração e silêncio ficam preservados; fala começa após a entrada visual.
 assert len(data)/rate<c['end']-c['start']-.35, 'Narração ultrapassa a cena'
 add(voice,data,c['start']+.28)
# Transições e feedback visual discretos; nenhum pico estridente.
for start in [4,13,22,32,39]:
 x=np.arange(int(rate*.45))/rate;noise=rng.normal(0,1,len(x));kernel=np.ones(20)/20
 air=np.convolve(noise,kernel,mode='same');sweep=.05*air*np.sin(np.pi*x/.45)**2
 add(effects,sweep,start-.23,-.35);add(effects,sweep[::-1],start-.16,.35)
for start in [6,9.4,15,28.8,35.8,40]:
 add(effects,note(783.99,.45,.055),start,-.15);add(effects,note(1174.66,.4,.022),start+.05,.15)
# Música recua durante a fala; ataque rápido e retorno suave.
activity=np.abs(voice)>.008
# Janela de 250ms protege finais de palavras sem bombeamento.
from scipy.ndimage import maximum_filter1d,gaussian_filter1d
coarse=activity.reshape(-1,480).max(axis=1).astype(float)
coarse=gaussian_filter1d(maximum_filter1d(coarse,size=25),sigma=4)
presence=np.interp(np.arange(n)/480,np.arange(len(coarse)),coarse)
duck=1-.63*presence
mix=music*duck[:,None]+effects+voice[:,None]
fade=np.minimum(t/1.2,1)*np.minimum((duration-t)/1.2,1);mix*=fade[:,None]
peak=np.max(np.abs(mix));mix*=min(1,.93/max(peak,.001))
with tempfile.TemporaryDirectory() as tmp:
 wav=Path(tmp)/'mix.wav';wavfile.write(wav,rate,(mix*32767).astype(np.int16))
 out=root/'assets/audio/soundtrack.m4a'
 subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(wav),'-af','loudnorm=I=-16:TP=-1.5:LRA=9','-ar','48000','-c:a','aac','-b:a','160k',str(out)],check=True)
print(f'Trilha criada: {duration}s, estéreo, narração + música original + efeitos.')
