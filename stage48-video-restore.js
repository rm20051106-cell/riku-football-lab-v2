/* Stage 48: resumable per-video recovery, streaming SHA-256, and audit history. */
(function () {
  "use strict";
  const JOB_KEY = "rikuVideoRestoreJob_v1";
  const HISTORY_KEY = "rikuVideoBackupHistory_v1";
  const CHUNK = 2 * 1024 * 1024;
  let paused = false;
  let active = false;
  let selectedFiles = [];

  const K = new Uint32Array([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
  ]);
  const rotr=(x,n)=>(x>>>n)|(x<<(32-n));
  class SHA256 {
    constructor(){this.h=new Uint32Array([0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]);this.buf=new Uint8Array(64);this.used=0;this.bytes=0;}
    block(b){const w=new Uint32Array(64);for(let i=0;i<16;i++)w[i]=((b[i*4]<<24)|(b[i*4+1]<<16)|(b[i*4+2]<<8)|b[i*4+3])>>>0;for(let i=16;i<64;i++){const x=w[i-15],y=w[i-2],s0=rotr(x,7)^rotr(x,18)^(x>>>3),s1=rotr(y,17)^rotr(y,19)^(y>>>10);w[i]=(w[i-16]+s0+w[i-7]+s1)>>>0;}let [a,c,d,e,f,g,h,j]=this.h;for(let i=0;i<64;i++){const s1=rotr(f,6)^rotr(f,11)^rotr(f,25),ch=(f&g)^(~f&h),t1=(j+s1+ch+K[i]+w[i])>>>0,s0=rotr(a,2)^rotr(a,13)^rotr(a,22),maj=(a&c)^(a&d)^(c&d),t2=(s0+maj)>>>0;j=h;h=g;g=f;f=(e+t1)>>>0;e=d;d=c;c=a;a=(t1+t2)>>>0;}const v=[a,c,d,e,f,g,h,j];for(let i=0;i<8;i++)this.h[i]=(this.h[i]+v[i])>>>0;}
    update(data){this.bytes+=data.length;let p=0;if(this.used){const n=Math.min(64-this.used,data.length);this.buf.set(data.subarray(0,n),this.used);this.used+=n;p=n;if(this.used===64){this.block(this.buf);this.used=0;}}while(p+64<=data.length){this.block(data.subarray(p,p+64));p+=64;}if(p<data.length){this.buf.set(data.subarray(p),0);this.used=data.length-p;}return this;}
    digest(){const bits=this.bytes*8;this.buf[this.used++]=0x80;if(this.used>56){this.buf.fill(0,this.used);this.block(this.buf);this.used=0;}this.buf.fill(0,this.used,56);const hi=Math.floor(bits/0x100000000),lo=bits>>>0;for(let i=0;i<4;i++){this.buf[56+i]=(hi>>>(24-i*8))&255;this.buf[60+i]=(lo>>>(24-i*8))&255;}this.block(this.buf);return Array.from(this.h,x=>x.toString(16).padStart(8,"0")).join("");}
  }
  const yieldUI=()=>new Promise(resolve=>setTimeout(resolve,0));
  async function hashBlob(blob,onProgress){
    const hash=new SHA256();let offset=0;
    while(offset<blob.size){if(paused)throw new Error("一時停止しました");const end=Math.min(blob.size,offset+CHUNK);const bytes=new Uint8Array(await blob.slice(offset,end).arrayBuffer());hash.update(bytes);offset=end;if(onProgress)onProgress(offset/blob.size);await yieldUI();if(paused)throw new Error("一時停止しました");}
    return hash.digest();
  }
  function readJob(){try{return JSON.parse(localStorage.getItem(JOB_KEY)||"null")}catch(_){return null}}
  function saveJob(job){localStorage.setItem(JOB_KEY,JSON.stringify(job));}
  function history(){try{return JSON.parse(localStorage.getItem(HISTORY_KEY)||"[]")}catch(_){return []}}
  function addHistory(row){const rows=history();rows.unshift(row);localStorage.setItem(HISTORY_KEY,JSON.stringify(rows.slice(0,40)));}
  function panel(){
    let el=document.getElementById("stage48RestorePanel");if(el)return el;
    const anchor=document.getElementById("videoRestorePreview")||document.getElementById("videoImportProgress");
    if(!anchor?.parentElement)return null;
    el=document.createElement("section");el.id="stage48RestorePanel";el.className="note";el.style.marginTop="10px";
    el.innerHTML='<b>動画バックアップ運用（第48段階）</b><div id="stage48Status" class="tiny" aria-live="polite">SHA-256照合・中断再開・履歴に対応</div><div class="btnrow"><button type="button" class="secondary small" id="stage48Pause">一時停止</button><button type="button" class="secondary small" id="stage48Resume">選択した動画で再開</button><button type="button" class="secondary small" id="stage48Retry">失敗動画だけ再試行</button></div><div id="stage48Report" class="tiny" style="white-space:pre-wrap;margin-top:8px"></div><div id="stage48History" class="tiny" style="margin-top:8px"></div>';
    anchor.insertAdjacentElement("afterend",el);
    el.querySelector("#stage48Pause").addEventListener("click",()=>{paused=true;status("一時停止を要求しました。処理中の動画が安全な区切りに達すると停止します。");});
    el.querySelector("#stage48Resume").addEventListener("click",()=>document.getElementById("videoImportFiles")?.click());
    el.querySelector("#stage48Retry").addEventListener("click",()=>{const j=readJob();if(!j)return;const failed=new Set(j.items.filter(x=>x.status==="failed").map(x=>x.name+"|"+x.size+"|"+x.lastModified));const input=document.getElementById("videoImportFiles");if(input){input.dataset.stage48Retry="1";input.click();}});
    renderHistory();return el;
  }
  function status(message){const el=document.getElementById("stage48Status");if(el)el.textContent=message;}
  function renderHistory(){const el=document.getElementById("stage48History");if(!el)return;const rows=history();el.textContent=rows.length?"バックアップ・復元履歴（最新5件）\n"+rows.slice(0,5).map(x=>new Date(x.at).toLocaleString("ja-JP")+"｜"+x.action+"｜成功 "+x.success+"本／失敗 "+x.failed+"本｜"+(x.bytes/1048576).toFixed(1)+"MB").join("\n"):"バックアップ・復元履歴はまだありません。";}
  function report(job,heading){const ok=job.items.filter(x=>x.status==="done"),bad=job.items.filter(x=>x.status==="failed"),pending=job.items.filter(x=>x.status!=="done"&&x.status!=="failed");const lines=[heading,"対象 "+job.items.length+"本／完了 "+ok.length+"本／失敗 "+bad.length+"本／未処理 "+pending.length+"本","SHA-256照合：完了動画 "+ok.filter(x=>x.hash).length+"本","完了動画："+ok.map(x=>x.name).join("、"),bad.length?"失敗動画："+bad.map(x=>x.name+"（"+(x.error||"失敗")+"）").join("、"):"失敗動画なし","このレポートは端末内に保存されます。"];const el=document.getElementById("stage48Report");if(el)el.textContent=lines.join("\n");}
  async function run(files, retryOnly){
    if(active || !files?.length) return true;
    active=true;paused=false;selectedFiles=[...files];panel();
    // iOS/Safari may assign a different lastModified when the same backup is selected again.
    // Locate checkpoints by filename + size, then use SHA-256 to prove the bytes are identical.
    const stableKey=value=>value.name+"|"+value.size;
    const byKey=new Map(files.map(file=>[stableKey(file),file]));
    const old=readJob();
    let job=old&&old.items?.some(item=>item.status!=="done")?old:{id:"restore-"+Date.now(),action:"復元",at:new Date().toISOString(),items:[]};
    if(!job.items.length) job.items=files.map(file=>({name:file.name,size:file.size,lastModified:file.lastModified,status:"pending",hash:null,savedHash:null,error:null}));
    for(const file of files){
      const key=stableKey(file);
      if(!job.items.some(item=>stableKey(item)===key)) job.items.push({name:file.name,size:file.size,lastModified:file.lastModified,status:"pending",hash:null,savedHash:null,error:null});
    }
    const work=job.items.filter(item=>byKey.has(stableKey(item))&&(retryOnly?item.status==="failed":item.status!=="done"));
    if(!work.length){status("再開対象がありません。中断した動画ファイルを選び直してください。");active=false;return true;}
    saveJob(job);
    try{
      // Hash every selected source first. The existing Stage 47 batch transaction then
      // remains responsible for atomic writes/rollback across this batch.
      const ready=[];
      for(let i=0;i<work.length;i++){
        const item=work[i],file=byKey.get(stableKey(item));
        if(paused) break;
        try{
          status("元動画SHA-256計算中："+file.name+"（"+(i+1)+"/"+work.length+"）");
          const expectedHash=item.hash;
          const actualHash=await hashBlob(file,p=>status("元動画SHA-256計算中："+file.name+" "+Math.round(p*100)+"%"));
          if(expectedHash && expectedHash!==actualHash) throw new Error("同じファイル名・サイズですがSHA-256が異なります。別の動画を誤って選択していないか確認してください");
          item.hash=actualHash;item.lastModified=file.lastModified;item.status="verifying";item.error=null;saveJob(job);ready.push(file);
        }catch(error){
          if(paused || String(error?.message||error).includes("一時停止しました")){item.status="pending";item.error=null;}else{item.status="failed";item.error=String(error?.message||error).slice(0,240);}saveJob(job);
          if(paused) break;
        }
      }
      if(!paused && ready.length){
        status("Stage 47の一括事前検査・復元・ロールバック処理を実行中…");
        const priorBatchMode=window.__stage48BatchMode;
        const priorAlert=window.alert;
        window.__stage48BatchMode=true;
        window.alert=()=>{};
        try{const outcome=await window.runStage47VideoRestore(ready);const preview=document.getElementById("videoRestorePreview")?.textContent||"";if(outcome?.ok===false||outcome===false||/^(復元中止|復元失敗|復元をキャンセル)/.test(preview))throw new Error(outcome?.error||preview.split("\n")[0]||"Stage 47の事前検査・保存に失敗しました");}
        catch(error){for(const file of ready){const key=stableKey(file);const item=job.items.find(row=>stableKey(row)===key);if(item&&item.status!=="done"){item.status="failed";item.error=String(error?.message||error).slice(0,240);}}saveJob(job);report(job,"復元失敗レポート");}
        finally{window.alert=priorAlert;if(priorBatchMode===undefined)delete window.__stage48BatchMode;else window.__stage48BatchMode=priorBatchMode;}
        for(const file of ready){
          const key=stableKey(file);
          const item=job.items.find(row=>stableKey(row)===key);
          try{
            const match=file.name.match(/^riku-video__(.+?)__(.+)$/);
            if(!match) throw new Error("動画バックアップのファイル名形式が不正です");
            const storageKey=decodeURIComponent(match[1]);
            const saved=await getClipVideo(storageKey);
            if(!saved?.blob || saved.blob.size!==file.size) throw new Error("保存後の動画サイズ照合に失敗（Stage 47の復元処理が完了していない可能性）");
            const savedHash=await hashBlob(saved.blob,p=>status("保存後SHA-256照合中："+file.name+" "+Math.round(p*100)+"%"));
            if(savedHash!==item.hash) throw new Error("保存後SHA-256不一致");
            item.savedHash=savedHash;item.status="done";item.error=null;
          }catch(error){item.status="failed";item.error=String(error?.message||error).slice(0,240);}
          saveJob(job);report(job,"復元の進行レポート");await yieldUI();
        }
      }
      job.updatedAt=new Date().toISOString();saveJob(job);
      const pending=job.items.some(item=>item.status==="pending"||item.status==="verifying");
      const failed=job.items.filter(item=>item.status==="failed").length;
      const done=job.items.filter(item=>item.status==="done").length;
      const skipped=job.items.filter(item=>item.status==="done"&&item.duplicate===true).length;
      const imported=done-skipped;
      if(!pending && !paused){
        addHistory({at:new Date().toISOString(),action:"復元",success:done,failed,bytes:job.items.filter(item=>item.status==="done").reduce((n,item)=>n+item.size,0)});
        renderHistory();
        try{if(typeof scanSavedVideoIntegrity==="function")await scanSavedVideoIntegrity();if(typeof refreshVideoStorageStatus==="function")await refreshVideoStorageStatus();}catch(error){console.warn("Stage 48 final integrity scan",error);}
        window.alert("動画ファイルの復元が完了しました。\n新規保存・確認："+imported+"本\n同一動画のためスキップ："+skipped+"本\n未読込："+failed+"本\n保存後SHA-256照合："+done+"本\n設定画面の「動画と記録を照合する」から再生テストできます。");
      }
      // Release the run lock before exposing the retry-ready UI. A tap can arrive
      // as soon as status() updates the DOM; leaving active=true until finally would
      // silently discard that retry request on slower iPhone Safari / browser polling.
      active=false;
      status(paused?"一時停止しました。動画を同じファイル名で選び直すと続きから再開します。":pending?"未処理動画があります。選び直して再開してください。":failed?"完了（一部失敗）。失敗動画だけ再試行できます。":"全動画の復元とSHA-256照合が完了しました。");
      report(job,paused?"中断レポート":pending?"復元の進行レポート":"復元完了レポート");
    }finally{active=false;}
    return true;
  }
  window.hashStage48Blob=async blob=>{paused=false;return hashBlob(blob);};
  window.pauseStage48Restore=()=>{paused=true;};
  window.runStage48VideoRestore=files=>run(files,false);
  window.retryStage48FailedVideos=files=>run(files,true);
  window.addEventListener("change",event=>{
    if(event.target?.id!=="videoImportFiles")return;
    const files=[...(event.target.files||[])];if(!files.length)return;
    const retry=event.target.dataset.stage48Retry==="1";event.target.dataset.stage48Retry="0";
    if(window.__stage48Intercept){event.stopImmediatePropagation();event.preventDefault();(retry?window.retryStage48FailedVideos(files):window.runStage48VideoRestore(files));}
  },true);
  window.addEventListener("load",()=>{panel();const job=readJob();if(job){report(job,"前回の復元状態");status("前回の処理状態を復元しました。同じ動画を選び直すと続きから再開できます。");}});
  window.addEventListener("pagehide",()=>{const job=readJob();if(job){job.updatedAt=new Date().toISOString();try{saveJob(job)}catch(e){}}});
  window.addEventListener("beforeunload",()=>{const job=readJob();if(active&&job){try{saveJob(job)}catch(e){}}});
  // Backup export audit: record JSON backup generation without altering its payload.
  const originalExportData=window.exportData;
  if(typeof originalExportData==="function")window.exportData=async function(){const before=history().length;await originalExportData();if(history().length===before){addHistory({at:new Date().toISOString(),action:"記録JSONバックアップ",success:1,failed:0,bytes:0});renderHistory();}};
  const originalPrepareVideoExport=window.prepareVideoExport;
  if(typeof originalPrepareVideoExport==="function")window.prepareVideoExport=async function(){await originalPrepareVideoExport();try{const stats=await readVideoStorageUsage();addHistory({at:new Date().toISOString(),action:"動画バックアップ一覧作成",success:stats.count,failed:stats.invalid,bytes:stats.bytes});renderHistory();}catch(error){console.warn("Stage 48 backup history",error);}};
  document.addEventListener("visibilitychange",()=>{if(document.hidden&&active){paused=true;status("Safariがバックグラウンドになりました。安全な区切りで一時停止します。前面に戻ったら動画を選び直して再開してください。");}});
  window.__stage48Intercept=true;
  panel();
})();