
/* Gera o MP4 original a partir da composição HTML; requer Playwright e FFmpeg. */
const fs=require('node:fs/promises'),path=require('node:path'),{spawn}=require('node:child_process'),{chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
let browser,encoder;try{
let html=await fs.readFile(path.join(root,'assets/nelvo-film.html'),'utf8');
for(const [tag,file,type] of [['LOGO','nelvo-logo-transparent.png','image/png'],['CONNECTED','media/nelvo-connected.png','image/png'],['STUDIO','media/nelvo-studio.png','image/png']])html=html.replaceAll('%'+tag+'%','data:'+type+';base64,'+(await fs.readFile(path.join(root,'atendeai/static',file))).toString('base64'));
browser=await chromium.launch({headless:true,...(process.env.PANEL_CHROME_PATH?{executablePath:process.env.PANEL_CHROME_PATH}:{}),...(process.env.PANEL_CHROME_ARGS?{args:JSON.parse(process.env.PANEL_CHROME_ARGS)}:{})});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});await page.setContent(html);await page.evaluate(async()=>{await document.fonts.ready;await Promise.all([...document.images].map(i=>i.decode()));});
await page.evaluate(()=>renderAt(1.4));await page.screenshot({path:path.join(root,'atendeai/static/media/nelvo-poster.jpg'),type:'jpeg',quality:92});
for(const time of [1.4,6.3,11,16,21.8,25]){await page.evaluate(time=>renderAt(time),time);await page.screenshot({path:'/tmp/atendeai-panel-check/film-'+time+'.jpg',type:'jpeg',quality:92});}
const target=path.join(root,'atendeai/static/media/nelvo-intro.mp4');
encoder=spawn('ffmpeg',['-hide_banner','-loglevel','error','-y','-f','image2pipe','-vcodec','mjpeg','-framerate','24','-i','pipe:0','-an','-c:v','libx264','-threads','2','-preset','medium','-crf','24','-pix_fmt','yuv420p','-movflags','+faststart',target],{stdio:['pipe','ignore','pipe']});
let logs='';encoder.stderr.on('data',d=>logs+=d);const done=new Promise((resolve,reject)=>{encoder.on('error',reject);encoder.on('exit',code=>code===0?resolve():reject(new Error(logs)))});
for(let frame=0;frame<624;frame++){await page.evaluate(t=>renderAt(t),Math.max(.01,frame/24));const jpeg=await page.screenshot({type:'jpeg',quality:90});await new Promise((resolve,reject)=>encoder.stdin.write(jpeg,e=>e?reject(e):resolve()));if(frame%120===0)console.log('Renderizando vídeo:',frame,'/ 624 quadros');}
encoder.stdin.end();await done;console.log('MP4 criado:',target,(await fs.stat(target)).size,'bytes');
}finally{if(browser)await browser.close();if(encoder&&!encoder.killed)encoder.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
