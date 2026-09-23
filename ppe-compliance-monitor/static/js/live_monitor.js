// Live monitor — browser webcam -> /api/process-frame/
var LiveMonitor = (function(){
  let cfg = {processUrl:'/api/process-frame/', csrfToken:''};
  let video, canvas, ctx, placeholder, statusEl, fpsEl, latencyEl, frameCounterEl;
  let streaming=false, sendTimer=null, frameCount=0, lastFpsTime=Date.now(), fpsFrames=0;
  let stream=null;

  function init(opts){
    cfg = Object.assign(cfg, opts);
    video = document.getElementById('video');
    canvas = document.getElementById('canvas');
    ctx = canvas.getContext('2d');
    placeholder = document.getElementById('live-placeholder');
    statusEl = document.getElementById('ov-status');
    fpsEl = document.getElementById('fps-badge');
    latencyEl = document.getElementById('latency-badge');
    frameCounterEl = document.getElementById('frame-counter');

    document.getElementById('btn-start').addEventListener('click', start);
    document.getElementById('btn-stop').addEventListener('click', stop);
    document.getElementById('btn-capture').addEventListener('click', capture);
    document.getElementById('conf-slider').addEventListener('input', e=>{
      document.getElementById('conf-val').textContent=parseFloat(e.target.value).toFixed(2);
    });

    // Set canvas size
    canvas.width=640; canvas.height=480;
    ctx.fillStyle='#000'; ctx.fillRect(0,0,canvas.width,canvas.height);
    ctx.fillStyle='#64748b'; ctx.font='14px Inter';
    ctx.textAlign='center'; ctx.fillText('Press Start Camera to begin', canvas.width/2, canvas.height/2);

    console.log('LiveMonitor ready, processUrl=', cfg.processUrl);
  }

  async function start(){
    try{
      stream = await navigator.mediaDevices.getUserMedia({video:{width:1280,height:720}, audio:false});
      video.srcObject=stream;
      await video.play();
      streaming=true;
      document.getElementById('btn-start').disabled=true;
      document.getElementById('btn-stop').disabled=false;
      document.getElementById('btn-capture').disabled=false;
      if(placeholder) placeholder.style.display='none';
      if(statusEl) statusEl.textContent='Streaming — detecting...';
      // canvas size to video
      const w=video.videoWidth||640, h=video.videoHeight||480;
      canvas.width=w; canvas.height=h;
      schedule();
      updateFpsLoop();
    }catch(e){
      alert('Camera failed: '+e.message+'\nTry upload instead or check permissions.');
      if(statusEl) statusEl.textContent='Camera error: '+e.message;
    }
  }

  function stop(){
    streaming=false;
    if(sendTimer) clearTimeout(sendTimer);
    if(stream){ stream.getTracks().forEach(t=>t.stop()); stream=null; }
    video.srcObject=null;
    document.getElementById('btn-start').disabled=false;
    document.getElementById('btn-stop').disabled=true;
    document.getElementById('btn-capture').disabled=true;
    if(placeholder) placeholder.style.display='block';
    if(statusEl) statusEl.textContent='Camera stopped';
  }

  function schedule(){
    if(!streaming) return;
    const interval = parseInt(document.getElementById('interval-sel').value)||500;
    sendTimer=setTimeout(async ()=>{
      await sendFrame();
      schedule();
    }, interval);
  }

  async function sendFrame(){
    if(!streaming || video.readyState < 2) return;
    // Draw video to temp canvas to get base64
    const temp = document.createElement('canvas');
    temp.width=video.videoWidth; temp.height=video.videoHeight;
    temp.getContext('2d').drawImage(video,0,0);
    const dataUrl=temp.toDataURL('image/jpeg', 0.78);
    const conf=document.getElementById('conf-slider').value;

    const t0=performance.now();
    try{
      const res=await fetch(cfg.processUrl, {
        method:'POST',
        headers:{'Content-Type':'application/json', 'X-CSRFToken': cfg.csrfToken},
        body: JSON.stringify({image:dataUrl, confidence:parseFloat(conf)})
      });
      const latency=Math.round(performance.now()-t0);
      if(latencyEl) latencyEl.textContent=latency+' ms';
      if(!res.ok){ const err=await res.json().catch(()=>({})); throw new Error(err.error||res.statusText); }
      const data=await res.json();
      frameCount++; if(frameCounterEl) frameCounterEl.textContent='Frames: '+frameCount;
      fpsFrames++;
      // Draw annotated image
      if(data.annotated_image){
        const img=new Image();
        img.onload=()=>{
          // Fit to canvas size (already set to video size)
          ctx.clearRect(0,0,canvas.width,canvas.height);
          ctx.drawImage(img,0,0,canvas.width,canvas.height);
        };
        img.src=data.annotated_image;
      }
      // Update compliance UI
      if(window.updateComplianceUI && data.compliance){
        window.updateComplianceUI(data.compliance);
      } else if(data.compliance){
        const c=data.compliance;
        const panel=document.getElementById('compliance-panel');
        if(panel){
          let html='';
          (c.violations||[]).forEach(v=> html+=`<div class="violation-alert mb-2 p-2 rounded small">🚨 Person #${v.person_id} missing: ${v.missing_items.join(', ')}</div>`);
          (c.compliant||[]).forEach(v=> html+=`<div class="compliant-status mb-2 p-2 rounded small">✅ Person #${v.person_id} compliant</div>`);
          if(!html) html='<div class="text-muted small text-center py-2">No persons detected</div>';
          panel.innerHTML=html;
        }
        document.getElementById('ov-persons').textContent=c.person_count||0;
        document.getElementById('ov-violations').textContent=(c.violations||[]).length;
        document.getElementById('ov-compliant').textContent=(c.compliant||[]).length;
      }
      if(statusEl) statusEl.textContent='Live • '+new Date().toLocaleTimeString()+' • '+latency+'ms';
    }catch(e){
      console.warn('frame send failed', e);
      if(statusEl) statusEl.textContent='Error: '+e.message;
    }
  }

  function capture(){
    const a=document.createElement('a');
    a.href=canvas.toDataURL('image/jpeg');
    a.download='ppe-capture-'+Date.now()+'.jpg';
    a.click();
  }

  function updateFpsLoop(){
    setInterval(()=>{
      const now=Date.now();
      const elapsed=(now-lastFpsTime)/1000;
      const fps=Math.round(fpsFrames/elapsed);
      if(fpsEl) fpsEl.textContent=(isFinite(fps)?fps:0)+' FPS';
      fpsFrames=0; lastFpsTime=now;
    },1000);
  }

  return {init, start, stop};
})();
