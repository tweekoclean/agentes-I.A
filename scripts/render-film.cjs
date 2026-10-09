
/* Gera o MP4 original a partir da composição HTML; requer Playwright e FFmpeg. */
const fs=require('node:fs/promises'),path=require('node:path'),{spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
let browser,encoder;try{
await fs.access(path.join(root,'assets/audio/soundtrack.m4a'));
let html=await fs.readFile(path.join(root,'assets/nelvo-film.html'),'utf8');
for(const [tag,file,type] of [['LOGO','nelvo-logo-transparent.png','image/png'],['CONNECTED','media/nelvo-connected.png','image/png'],['STUDIO','media/nelvo-studio.png','image/png']])html=html.replaceAll('%'+tag+'%','data:'+type+';base64,'+(await fs.readFile(path.join(root,'atendeai/static',file))).toString('base64'));
browser=await chromium.launch({headless:true,...(process.env.PANEL_CHROME_PATH?{executablePath:process.env.PANEL_CHROME_PATH}:{}),...(process.env.PANEL_CHROME_ARGS?{args:JSON.parse(process.env.PANEL_CHROME_ARGS)}:{})});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1.5});await page.setContent(html);await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
await fs.mkdir('/tmp/atendeai-panel-check',{recursive:true});
await page.evaluate(()=>renderAt(1.4));await page.screenshot({path:path.join(root,'atendeai/static/media/nelvo-poster.jpg'),type:'jpeg',quality:96});
for(const time of [1.4,10.5,19,29.5,37.5,43]){await page.evaluate(time=>renderAt(time),time);await page.screenshot({path:'/tmp/atendeai-panel-check/film-'+time+'.jpg',type:'jpeg',quality:96});}
const target=path.join(root,'atendeai/static/media/nelvo-intro.mp4');
const script=JSON.parse(await fs.readFile(path.join(root,'assets/film-script.json'),'utf8'));
const frames=script.duration*30;
encoder=spawn('ffmpeg',['-hide_banner','-loglevel','error','-y','-f','image2pipe','-vcodec','mjpeg','-framerate','30','-i','pipe:0','-i',path.join(root,'assets/audio/soundtrack.m4a'),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-threads','2','-preset','medium','-crf','19','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart','-t',String(script.duration),target],{stdio:['pipe','ignore','pipe']});
let logs='';encoder.stderr.on('data',d=>logs+=d);const done=new Promise((resolve,reject)=>{encoder.on('error',reject);encoder.on('exit',code=>code===0?resolve():reject(new Error(logs)))});
encoder.stdin.on('error',()=>{});done.catch(()=>{});
for(let frame=0;frame<frames;frame++){await page.evaluate(t=>renderAt(t),Math.max(.01,frame/30));const jpeg=await page.screenshot({type:'jpeg',quality:97});await new Promise((resolve,reject)=>encoder.stdin.write(jpeg,e=>e?reject(e):resolve()));if(frame%150===0)console.log('Renderizando vídeo:',frame,'/',frames,'quadros');}
encoder.stdin.end();await done;console.log('MP4 criado:',target,(await fs.stat(target)).size,'bytes');
}finally{if(browser)await browser.close();if(encoder&&!encoder.killed)encoder.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
