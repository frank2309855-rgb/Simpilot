'use strict';
const TOKEN=window.WORKBENCH_TOKEN;
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fields=['label','data_kind','ratio_definition','q_unit','time_unit','time_origin','structure_definition','conditions_note'];
const numeric=['time_start','time_end','q_min','q_max','min_prominence','competitor_fraction','stability_tolerance','blocks'];
const kernelLabels={linear:'Linear',rbf:'RBF',matern_32:'Matérn 3/2',matern_52:'Matérn 5/2',rational_quadratic:'Rational Quadratic'};
function collectKernels(){return Object.keys(kernelLabels).filter(k=>$('kernel_'+k).checked)}
function fillKernels(value){const list=value===undefined?['linear']:value;if(!Array.isArray(list)||!list.length||list.some(k=>!Object.hasOwn(kernelLabels,k))||new Set(list).size!==list.length)throw new Error('設定檔的 kernel 選項無效。');for(const k of Object.keys(kernelLabels))$('kernel_'+k).checked=list.includes(k);updateKernelSummary();}
function updateKernelSummary(){const list=collectKernels();$('kernelSummary').textContent=list.length?'已選 '+list.length+' 種：'+list.map(k=>kernelLabels[k]).join('、'):'請至少選一種 kernel 才能開始訓練。';$('selectedKernelTitle').textContent=list.length?'Ratio · '+list.map(k=>kernelLabels[k]).join(' / '):'尚未選擇';gate();}
let displayedRunId=null,pendingRunDeletion=null;
let analysis=null,busy=false,legacyRatios=[],rawExtraction=null,rawJobId=null,drivePlan=null,qualityRangeProposal=null;
const driveFields=['max_download_mib','max_frame_mib','reserve_disk_mib'];
const rawNumeric=["type_a","type_b","step_start","step_end","stride","length_scale","time_scale","time_offset","q_max","dq"];
const rawText=["length_unit","time_unit","normalization"];
const colors=['#c78c37','#718ab0','#b47791','#769f75','#bd6a48','#8d7ca6','#509598','#b1a340','#b26c7e','#6c8790'];
function page(index){document.querySelectorAll('.page').forEach((p,i)=>p.classList.toggle('active',i===index));document.querySelectorAll('nav button').forEach((b,i)=>{if(i===index)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current')});window.scrollTo({top:0,behavior:'instant'});}
document.querySelectorAll('[data-nav]').forEach(b=>b.addEventListener('click',()=>page(Number(b.dataset.nav))));
function error(e,scroll=true){$('error').textContent=e.message||String(e);$('error').classList.remove('hidden');if(scroll)$('error').scrollIntoView({block:'center',behavior:'smooth'});} 
function clearError(){$('error').classList.add('hidden');}
async function api(path,body){
  if(!['http:','https:'].includes(location.protocol))throw new Error('請用 start_workbench.cmd 啟動工作台；直接開啟 HTML 檔無法讀取本機資料。');
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),15000);
  try{
    const r=await fetch(path,{method:body===undefined?'GET':'POST',signal:controller.signal,headers:{'Content-Type':'application/json','X-Workbench-Token':TOKEN},...(body===undefined?{}:{body:JSON.stringify(body)})});
    let d;try{d=await r.json()}catch{throw new Error('後端沒有回傳可讀取的結果。請保存設定，重新啟動工作台後重新整理頁面。')}
    if(!r.ok)throw new Error(d.error||'請求失敗');return d;
  }catch(e){
    if(e.name==='AbortError')throw new Error('等待超過 15 秒，已結束本次等候。請確認工作台仍在執行，或雲端磁碟是否正在下載，再重試。');
    if(e instanceof TypeError)throw new Error('無法連到本機工作台。請保持啟動視窗開啟；若已關閉，重新執行 start_workbench.cmd 並重新整理頁面。');
    throw e;
  }finally{clearTimeout(timer)}
}
function gate(){const ready=analysis?.ready===true;$('train').disabled=busy||!collectKernels().length||!ready||!$('reviewed').checked||!$('review_note').value.trim();$('downloadReview').disabled=busy||!analysis;$('trainingGate').textContent=ready?(isLowQ()?'五個配方的低 q 資料完整。確認曲線並填入判讀紀錄後即可訓練。':isM()?'五個配方的 M 可計算。確認曲線並填入判讀紀錄後即可訓練。':'五個配方通過本次峰值規則。確認曲線並填入判讀紀錄後即可訓練。'):analysis?'仍有配方需要確認，請返回資料檢查。':(isLowQ()?'請先完成五個配方的低 q 資料檢查。':isM()?'請先完成五個配方的 M 資料檢查。':'請先完成五個配方的 q* 品質檢查。');$('trainingGate').classList.toggle('green',ready);}
function setBusy(value,text){busy=value;document.querySelectorAll('input,select,textarea,button').forEach(e=>{if(!e.dataset.nav)e.disabled=value});$('status').classList.toggle('busy',value);if(text)$('statusText').textContent=text;gate();$('cancelRaw').disabled=!value||!rawJobId;if($('ratioPreview0'))updateRatios();}
function invalidate(){if(analysis){analysis=null;$('qualityResults').className='empty';$('qualityResults').textContent='設定或資料已變更，請重新檢查。';$('qualityCount').textContent='需要重新檢查';}$('reviewed').checked=false;gate();$('demoBanner').classList.toggle('hidden',$('data_kind').value!=='synthetic_demo');}
function rowValue(i,key){return document.querySelector(`[data-row="${i}"][data-key="${key}"]`).value;}
function ratioValue(a,b,mode){
  if(a===''||b==='')return null;
  a=Number(a);b=Number(b);
  if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b<0||Math.max(a,b)===0)return null;
  if(mode==='quotient')return b>0&&Number.isFinite(a/b)?a/b:null;
  const scale=Math.max(a,b);return(a/scale)/(a/scale+b/scale);
}
function updateRatios(){
  const mode=$('ratio_encoding').value;
  for(let i=0;i<5;i++){
    const a=document.querySelector(`[data-row="${i}"][data-key="amount_a"]`),b=document.querySelector(`[data-row="${i}"][data-key="amount_b"]`);
    a.disabled=b.disabled=busy||mode==='legacy_scalar';
    const value=mode==='legacy_scalar'?legacyRatios[i]:ratioValue(a.value,b.value,mode);
    $('ratioPreview'+i).textContent=value==null?'尚未填妥':String(Number(Number(value).toPrecision(8)));
    if(value===0)$('ratioPreview'+i).textContent='0';
    $('ratioPreview'+i).title=value==null?'請填入有效 A、B 數值':String(value);
  }
  $('encodingNote').textContent=mode==='legacy_scalar'?'載入的是舊版單值 ratio，原值完整保留。若要改用 A:B，請明確選擇換算方式後填入 A、B；系統不會猜測舊比例定義。':`GP input = ${mode==='fraction'?'A/(A+B)':'A/B'}。下表保留原始 A:B，標準化仍在各訓練折內執行。`;
}
function renderRows(rows){
  legacyRatios=rows.map(r=>r.ratio??null);
  $('recipes').innerHTML=rows.map((r,i)=>`<tr><td class="recipe"><input aria-label="配方 ${i+1} 名稱" data-row="${i}" data-key="label" value="${esc(r.label)}" placeholder="配方 ${i+1}"></td><td class="amount"><input aria-label="配方 ${i+1} A" data-row="${i}" data-key="amount_a" type="number" min="0" step="1" value="${esc(r.amount_a)}" placeholder="A"></td><td class="amount"><input aria-label="配方 ${i+1} B" data-row="${i}" data-key="amount_b" type="number" min="0" step="1" value="${esc(r.amount_b)}" placeholder="B"></td><td class="ratio"><output id="ratioPreview${i}" aria-label="配方 ${i+1} GP ratio"></output></td><td class="seed"><input aria-label="配方 ${i+1} seed" data-row="${i}" data-key="seed_id" value="${esc(r.seed_id)}"></td><td class="path"><input aria-label="配方 ${i+1} 資料路徑" data-row="${i}" data-key="path" value="${esc(r.path)}" placeholder="CSV 模式請填入 S(q,t) 檔案完整路徑"></td><td><button data-inspect="${i}">檢查路徑</button><button data-choose="${i}" class="choose-folder">選資料夾</button></td></tr><tr><td colspan="7" class="row-note"><div class="path-result hidden" id="pathNote${i}" role="status" aria-live="polite"></div></td></tr>`).join('');
  $('recipes').querySelectorAll('input').forEach(e=>e.addEventListener('input',()=>{updateRatios();invalidate();if(e.dataset.key==='path'){$('pathNote'+e.dataset.row).classList.add('hidden');$('pathNote'+e.dataset.row).probeData=null;invalidateRaw()}}));
  $('recipes').querySelectorAll('[data-inspect]').forEach(e=>e.addEventListener('click',()=>inspectRow(Number(e.dataset.inspect))));$('recipes').querySelectorAll('[data-choose]').forEach(e=>e.addEventListener('click',()=>chooseFolder(Number(e.dataset.choose))));updateRatios();sourceMode();
}
function collect(){
 const p=Object.fromEntries(fields.map(k=>[k,$(k).value]));p.project_format_version=7;p.kernel_choices=collectKernels();p.target_kind=$('target_kind').value;p.ratio_encoding=$('ratio_encoding').value;p.source_mode=$('source_mode').value;p.raw_settings=collectRaw();p.drive_options=collectDrive();p.extraction_id=rawExtraction?.id??null;p.experiment_profiles=collectProfiles();p.experiment_window={start:$('scatter_start').value,end:$('scatter_end').value};
 p.settings=Object.fromEntries(numeric.map(k=>[k,$(k).value.trim()===''?null:Number($(k).value)]));
 p.q_settings={...p.settings};p.m_settings=collectM();p.low_q_settings=collectLowQ();if(isM())p.settings={...p.m_settings};if(isLowQ())p.settings={...p.low_q_settings};
 p.rows=Array.from({length:5},(_,i)=>{
   const row=Object.fromEntries(['label','seed_id','path'].map(k=>[k,rowValue(i,k)]));
   if(p.ratio_encoding==='legacy_scalar')row.ratio=legacyRatios[i];
   else {row.amount_a=rowValue(i,'amount_a')===''?null:Number(rowValue(i,'amount_a'));row.amount_b=rowValue(i,'amount_b')===''?null:Number(rowValue(i,'amount_b'));row.ratio=ratioValue(rowValue(i,'amount_a'),rowValue(i,'amount_b'),p.ratio_encoding)}
   return row;
 });return p;
}
function fill(p){
 if(!p||!Array.isArray(p.rows)||p.rows.length!==5||!p.settings)throw new Error('設定檔需包含五列 rows 與 settings。');
 fillKernels(p.kernel_choices);
 const mode=p.ratio_encoding||'legacy_scalar';if(!['fraction','quotient','legacy_scalar'].includes(mode))throw new Error('設定檔中的比例換算方式不支援。');
 if(p.source_mode&&!['raw','csv','drive'].includes(p.source_mode))throw new Error('設定檔中的資料來源模式不支援。');
 drivePlan=null;driveFields.forEach(k=>{if(p.drive_options?.[k]!==undefined)$('drive_'+k).value=p.drive_options[k]});
 clearQualityRange();fillProfiles(p);$('source_mode').value=p.source_mode||'csv';rawExtraction=null;for(const k of [...rawNumeric,...rawText]){if(p.raw_settings?.[k]!==undefined)$('raw_'+k).value=p.raw_settings[k]}sourceMode();$('rawResults').innerHTML='';$('rawProgress').textContent='設定已載入；raw 模式請重新預覽／計算，內容相同時會重用快取。';
 const target=p.target_kind||'q_peak';if(!['q_peak','composition_strength','low_q_shell_mean'].includes(target))throw new Error('未知預測目標。');
 $('target_kind').value=target;
 const ls=p.low_q_settings||(target==='low_q_shell_mean'?p.settings:{q_min:0,q_max:.11,blocks:2});mNumeric.forEach(k=>$('low_'+k).value=ls[k]??'');
 const qs=p.q_settings||(target==='q_peak'?p.settings:{}),ms=p.m_settings||(target==='composition_strength'?p.settings:{time_start:qs.time_start,time_end:qs.time_end,q_min:0,q_max:.2,blocks:2});
 fields.forEach(k=>$(k).value=p[k]??'');numeric.forEach(k=>$(k).value=qs[k]??'');mNumeric.forEach(k=>$('m_'+k).value=ms[k]??'');$('ratio_encoding').value=mode;
 renderRows(p.rows);invalidate();updateTargetUI();$('statusText').textContent='設定已載入。請檢查定義與門檻，再執行品質檢查。';
}
function download(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function probeNextStep(data){
 if(data.kind==='sqt_csv')return isLowQ()?'請到低 q 資料檢查設定時間窗與頻帶；保留相鄰的 manifest.json。':isM()?'請到 M 資料檢查設定時間窗與頻帶；保留相鄰的 manifest.json。':'請到 q* 品質檢查設定時間窗與取峰規則。';
 if(data.kind==='directory')return '若這是 pos_* 資料夾，請選 Raw data 模式並完成 S(q,t) 計算，再檢查目前選擇的目標。CSV 模式需填入完整的 sqt.csv 檔案路徑。';
 return data.next_step||'';
}
function refreshProbeTargets(){for(const id of ['probeResult',...Array.from({length:5},(_,i)=>'pathNote'+i)]){const e=$(id);if(e?.probeData)showProbe(e,e.probeData)}}
function showProbe(element,data){
  element.probeData=data;
  const label={directory:'資料夾可讀',sqt_csv:'CSV 表頭符合',other_file:'檔案可讀，格式待處理'}[data.kind]||'讀取完成';
  element.className='path-result '+(data.usable_for_quality?'ok':'warn');
  const details=[...(data.entries||[]).map(e=>(e.directory?'[資料夾] ':'')+e.name),...(data.preview||[])];
  element.innerHTML=`<strong>${esc(label)}</strong><div>${esc(data.note)}</div><div class="hint">${esc(data.path)}${data.size!==undefined?' · '+data.size.toLocaleString()+' bytes':''}</div>${details.length?'<pre>'+esc(details.join(String.fromCharCode(10)))+'</pre>':''}<div>${esc(probeNextStep(data))}</div>`;
}
async function inspectRow(i){
 if($('source_mode').value==='drive'){$('pathNote'+i).className='path-result';$('pathNote'+i).textContent='Drive 模式請先登入、填妥五個資料夾網址與時間／q 設定，再按下方「預覽五個資料夾」；不會測試 H: 路徑。';return;}
 clearError();const p=rowValue(i,'path'),box=$('pathNote'+i),button=document.querySelector(`[data-inspect="${i}"]`);
 box.probeData=null;box.className='path-result';box.textContent='正在讀取路徑…（最長約 8 秒；雲端檔案可能需要下載）';button.textContent='讀取中…';setBusy(true,'測試本機路徑…');
 try{showProbe(box,await api('/api/inspect',{path:p}))}catch(e){box.className='path-result failure';box.textContent=e.message;error(e,false)}
 finally{button.textContent='檢查路徑';setBusy(false,'路徑檢查完成，結果顯示在該配方下方。');updateRatios()}
}
$('probe').onclick=async()=>{
 clearError();const box=$('probeResult');box.probeData=null;box.className='path-result';box.textContent='正在讀取路徑…（最長約 8 秒）';setBusy(true,'測試原路徑…');
 try{showProbe(box,await api('/api/inspect',{path:$('probePath').value}))}catch(e){box.className='path-result failure';box.textContent=e.message;error(e,false)}finally{setBusy(false,'路徑檢查完成，結果顯示在按鈕下方。');updateRatios()}
};
$('loadExample').onclick=async()=>{clearError();setBusy(true,'載入隨附五配方資料…');try{fill(await api('/api/example-project',{}));page(0);$('statusText').textContent='五配方範例已載入：1490–1499，低 q 頻帶 0–0.11；下一步進行資料檢查。'}catch(e){error(e)}finally{setBusy(false)}};
$('demo').onclick=async()=>{clearError();setBusy(true,'準備合成曲線…');try{fill(await api('/api/demo',{}));page(0)}catch(e){error(e)}finally{setBusy(false,'合成資料已載入；所有數值只供流程測試。');}};
$('exportProject').onclick=()=>download('gp-workbench-project.json',collect());$('importProject').onclick=()=>$('loadProject').click();$('loadProject').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>256*1024)throw new Error('設定檔超過 256 KiB。');fill(JSON.parse(await file.text()));clearError();page(0)}catch(e){error(e)}finally{$('loadProject').value=''}};
async function runJob(kind,payload){
 clearError();setBusy(true,kind==='analyze'?'正在檢查曲線…':kind==='choose_folder'?'請在本機視窗選資料夾…':'正在準備工作…');
 try{const {job_id}=await api('/api/'+kind,payload);if(['preview_raw','extract_raw'].includes(kind)){rawJobId=job_id;$('cancelRaw').disabled=false}
 for(;;){await new Promise(resolve=>setTimeout(resolve,600));const j=await api('/api/jobs/'+job_id);$('statusText').textContent=j.progress;if(rawJobId)$('rawProgress').textContent=j.progress;if(j.status==='failed')throw new Error(j.error);if(j.status==='complete')return j.result;}}
 finally{rawJobId=null;setBusy(false,'工作結束。');}
}
function chart(r){if(!r.q)return '';const w=800,h=230,pad={l:48,r:18,t:16,b:33};const all=[r.mean,...r.blocks.map(b=>b.mean)];const xmin=r.q[0],xmax=r.q.at(-1);let ymin=Infinity,ymax=-Infinity;all.forEach(a=>a.forEach(v=>{ymin=Math.min(ymin,v);ymax=Math.max(ymax,v)}));const range=ymax-ymin||1;ymin-=range*.08;ymax+=range*.08;const x=v=>pad.l+(v-xmin)/(xmax-xmin)*(w-pad.l-pad.r),y=v=>h-pad.b-(v-ymin)/(ymax-ymin)*(h-pad.t-pad.b);let svg=`<svg class="chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(r.label)} 的時間平均與分段 S 曲線">`;for(let i=0;i<5;i++){const v=xmin+(xmax-xmin)*i/4;svg+=`<line x1="${x(v)}" x2="${x(v)}" y1="${pad.t}" y2="${h-pad.b}" stroke="#e6ece7"/><text x="${x(v)}" y="${h-11}" text-anchor="middle">${v.toPrecision(3)}</text>`;}for(let i=0;i<3;i++){const v=ymin+(ymax-ymin)*i/2;svg+=`<text x="${pad.l-8}" y="${y(v)+4}" text-anchor="end">${v.toPrecision(3)}</text>`;}const line=(a,color,width)=>`<polyline points="${a.map((v,i)=>x(r.q[i]).toFixed(2)+','+y(v).toFixed(2)).join(' ')}" fill="none" stroke="${color}" stroke-width="${width}"/>`;r.blocks.forEach((b,i)=>svg+=line(b.mean,colors[i],1.4));svg+=line(r.mean,'#126957',2.8);if(r.q_peak!==null){svg+=`<line x1="${x(r.q_peak)}" x2="${x(r.q_peak)}" y1="${pad.t}" y2="${h-pad.b}" stroke="#126957" stroke-dasharray="4 4"/><text x="${x(r.q_peak)+6}" y="30">q* = ${r.q_peak.toPrecision(4)}</text>`;}return svg+'</svg>';}
function renderQuality(a){if(a.project.target_kind==='low_q_shell_mean')return renderLowQQuality(a);if(a.project.target_kind==='composition_strength')return renderMQuality(a);$('qualityCount').textContent=a.results.filter(r=>r.status==='ready').length+' / 5 通過篩查';$('qualityResults').className='';$('qualityResults').innerHTML=a.results.map(r=>`<article class="quality-card"><div class="quality-head"><div><h3>${esc(r.label)}</h3><span class="sub">ratio ${esc(r.ratio)}${r.amount_a!==undefined?' · A:B = '+esc(r.amount_a)+':'+esc(r.amount_b):''} · ${esc(r.seed_id)}${r.n_frames?' · '+r.n_frames+' frames':''}</span></div><span class="tag ${r.status==='ready'?'':r.status==='error'?'error':'warn'}">${r.status==='ready'?'通過宣告篩查':r.status==='error'?'資料無法檢查':'需要確認'}</span></div>${chart(r)}${r.blocks?`<div class="chart-note"><span><span class="legend-line" style="background:#126957"></span>全窗口平均</span>${r.blocks.map((b,i)=>`<span><span class="legend-line" style="background:${colors[i]}"></span>區塊 ${i+1}：${b.time_start}–${b.time_end}</span>`).join('')}</div><p class="sub">峰位最大差距：${r.peak_spread===null?'無法判定':r.peak_spread.toPrecision(4)}；q 網格間距：${r.q_grid_min_step.toPrecision(3)}–${r.q_grid_max_step.toPrecision(3)}</p>`:''}${r.reasons.length?`<div class="notice">${r.reasons.map(esc).join('<br>')}</div>`:'<p class="sub">峰位符合本次篩查規則。</p>'}${r.blocks?`<details><summary>查看分段峰位與來源紀錄</summary><pre>${esc(JSON.stringify({q_peak:r.q_peak,blocks:r.blocks.map(b=>({time:[b.time_start,b.time_end],q_peak:b.q_peak,reasons:b.reasons})),sha256:r.sha256,path:r.path,note:r.note},null,2))}</pre></details>`:''}</article>`).join('');gate();}
$('analyze').onclick=async()=>{try{analysis=null;gate();$('qualityCount').textContent='檢查中';$('qualityResults').className='empty';$('qualityResults').textContent='正在檢查這次設定；舊結果不再作為本次依據。';const result=await runJob('analyze',collect());analysis=result;$('reviewed').checked=false;renderQuality(result);$('statusText').textContent='品質紀錄已保存。請檢查每個配方的曲線與診斷。';}catch(e){error(e);$('qualityCount').textContent='檢查未完成';$('qualityResults').textContent='請修正上方錯誤後重新檢查。';gate();}};
$('downloadReview').onclick=()=>{if(analysis)download(analysis.project.target_kind==='low_q_shell_mean'?'low-q-quality-review.json':analysis.project.target_kind==='composition_strength'?'M-quality-review.json':'q-peak-quality-review.json',analysis)};
$('reviewed').onchange=gate;$('review_note').oninput=gate;
$('train').onclick=async()=>{try{const result=await runJob('train',{analysis_id:analysis.id,reviewed:$('reviewed').checked,review_note:$('review_note').value,kernel_choices:collectKernels()});showResult(result);page(3);await history();$('statusText').textContent='訓練與評估完成；全部候選模型已獨立保存。';}catch(e){error(e)}};
function showResult(r){displayedRunId=r.run_id;$('resultEmpty').classList.add('hidden');$('result').classList.remove('hidden');$('resultTitle').textContent=r.label+' · target: '+targetLabel(r.target_kind);$('resultKind').textContent=r.data_kind==='synthetic_demo'?'合成示範':'真實資料 / 探索性';$('resultKind').className='tag'+(r.data_kind==='synthetic_demo'?' warn':'');$('resultFolder').textContent='保存位置：'+r.folder;$('reportLink').href=r.report_url;$('reportFrame').src=r.report_url;$('trainingLink').href='/runs/'+r.run_id+'/training_data.csv';$('trainingLink').download='training_data.csv';$('auditLink').href='/runs/'+r.run_id+'/quality_review.json';$('auditLink').target='_blank';$('auditLink').rel='noopener';}
function closeRunDeletion(){pendingRunDeletion=null;$('deleteRunPanel').classList.add('hidden');$('deleteRunDetails').textContent='';}
async function prepareRunDeletion(entry){
 if(busy)return;closeRunDeletion();clearError();setBusy(true,'讀取這次執行的刪除範圍…');
 try{
  const r=await api('/api/history/delete-preview',{run_id:entry.run_id});pendingRunDeletion=r;
  $('deleteRunDetails').textContent=`名稱：${r.label}\n執行：${r.run_id}\n目標：${targetLabel(r.target_kind)}\n${r.file_count} 個檔案，約 ${(r.size_bytes/1024/1024).toFixed(2)} MiB\n位置：${r.folder}`;
  $('deleteRunPanel').classList.remove('hidden');$('deleteRunPanel').scrollIntoView({block:'center',behavior:'smooth'});
 }catch(e){error(e)}finally{setBusy(false,'請核對執行名稱及保存位置，再決定是否刪除。')}
}
async function confirmRunDeletion(){
 if(busy||!pendingRunDeletion)return;const r=pendingRunDeletion;clearError();setBusy(true,'正在刪除選定的執行紀錄…');
 try{
  await api('/api/history/delete',{run_id:r.run_id,fingerprint:r.fingerprint,confirmed:true});closeRunDeletion();
  if(displayedRunId===r.run_id){displayedRunId=null;$('reportFrame').src='about:blank';$('result').classList.add('hidden');$('resultEmpty').classList.remove('hidden');$('resultEmpty').textContent='這份執行紀錄已刪除，可從下方選擇其他報告。';for(const id of ['reportLink','trainingLink','auditLink'])$(id).removeAttribute('href');}
  $('historyNotice').textContent=`已刪除 ${r.run_id}。來源資料與其他執行紀錄保留。`;await history();
 }catch(e){closeRunDeletion();error(e);$('historyNotice').textContent='未能確認刪除完成，請重新整理紀錄查看目前狀態。';await history()}
 finally{setBusy(false,'執行紀錄管理結束。')}
}
async function history(){try{const entries=await api('/api/history');$('history').innerHTML=entries.length?entries.map((e,i)=>`<div class="quality-head" style="padding:12px 0;border-bottom:1px solid #edf0ed"><div><strong>${esc(e.label)}</strong><div class="sub">${esc(e.run_id)} · ${targetLabel(e.target_kind)} · ${esc((e.kernel_choices||['linear']).map(k=>kernelLabels[k]||k).join(' / '))} · ${e.data_kind==='synthetic_demo'?'合成示範':'真實資料'}</div><div class="hint" style="overflow-wrap:anywhere">${esc(e.folder)}</div></div><div class="actions"><button data-history="${i}">查看報告</button><button data-delete-run="${i}" ${busy?'disabled':''}>刪除紀錄</button></div></div>`).join(''):'目前沒有保存紀錄。';$('history').querySelectorAll('[data-history]').forEach(b=>b.onclick=()=>{showResult(entries[Number(b.dataset.history)]);page(3)});$('history').querySelectorAll('[data-delete-run]').forEach(b=>b.onclick=()=>prepareRunDeletion(entries[Number(b.dataset.deleteRun)]))}catch(e){$('history').textContent=e.message}}
$('confirmDeleteRun').onclick=confirmRunDeletion;$('cancelDeleteRun').onclick=closeRunDeletion;

function collectRaw(){
 const s={periodic:true};for(const k of rawNumeric){const v=$('raw_'+k).value.trim();s[k]=v===''?null:Number(v)}for(const k of rawText)s[k]=$('raw_'+k).value.trim();return s;
}
function sourceMode(){updateWindowControls();const mode=$('source_mode').value,isRaw=mode!=='csv',isDrive=mode==='drive';$('rawPanel').classList.toggle('hidden',!isRaw);$('drivePanel').classList.toggle('hidden',!isDrive);$('localProbePanel').classList.toggle('hidden',isDrive);document.querySelectorAll('.choose-folder').forEach(e=>e.classList.toggle('hidden',mode!=='raw'));document.querySelectorAll('[data-inspect]').forEach(e=>{e.classList.toggle('hidden',isDrive)});document.querySelectorAll('[data-key="path"]').forEach(e=>e.placeholder=isDrive?'https://drive.google.com/drive/folders/資料夾ID':isRaw?'包含 pos_數字 的完整資料夾路徑':'S(q,t) CSV 完整路徑');$('rawReadHint').textContent=isDrive?'先預覽選定時間範圍與傳輸量，再計算。計算時下載選定 frame 至記憶體；取消在目前區塊結束後生效。':'先預覽，再計算選定 frame。H: 讀取可能觸發雲端下載與快取；取消在目前區塊結束後生效。';}
async function applyCommonTimeWindow(prefix){
 clearError();setBusy(true,'正在讀取已完成資料的共同時間範圍…');let message='時間窗未變更。';
 const hint=$(prefix+'WindowHint');
 try{
  const p=$('source_mode').value==='csv'?await api('/api/csv-window',{paths:Array.from({length:5},(_,i)=>rowValue(i,'path'))}):qualityRangeFromExtraction();
  if(p.maxBlocks<2)throw new Error('共同時間窗每份不足四個 frame，無法分成至少兩段；設定未變更。');
  $(prefix+'time_start').value=String(p.range.time_start);$(prefix+'time_end').value=String(p.range.time_end);invalidate();
  const blocks=Number($(prefix+'blocks').value);
  message=`已帶入共同時間窗 ${p.range.time_start}–${p.range.time_end}，每份至少 ${p.minFrames} 個 frame。${!Number.isInteger(blocks)||blocks<2||blocks>p.maxBlocks?' 目前分段數不適用，請填入 2–'+p.maxBlocks+' 的整數。':''}`;
  hint.textContent=message;
 }catch(e){hint.textContent=e.message;error(e)}finally{setBusy(false,message)}
}
function updateWindowControls(){
 const csv=$('source_mode').value==='csv';
 for(const [id,prefix] of [['qUseDataWindow',''],['mUseRawWindow','m_'],['lowUseRawWindow','low_']]){
  $(id).textContent=csv?'從五份 CSV 帶入共同時間窗':'從本次 S(q,t) 結果帶入共同時間窗';
  $(prefix+'WindowHint').textContent=csv?'讀取五份 CSV 的共同時間端點，q 範圍與分段數維持原值。':'使用本次已完成的五份 S(q,t) 計算紀錄。';
 }
 $('suggestQualityRange').classList.toggle('hidden',csv);$('applyQualityRange').classList.toggle('hidden',csv);$('qualityRangeHint').classList.toggle('hidden',csv);
}
function clearQualityRange(){
 qualityRangeProposal=null;
 $('qualityRangeHint').textContent='完成五份 S(q,t) 後，可取得共同 q 與時間範圍。';
}
function qualityRangeFromExtraction(){
 if(!rawExtraction||rawExtraction.results?.length!==5)throw new Error('請先完成本次五份 S(q,t) 計算。此按鈕只使用已完成結果，不會下載或重新計算；目前不適用直接匯入 CSV。');
 const summaries=rawExtraction.results.map(r=>r.summary);
 for(const r of summaries){
  if(!r||!Array.isArray(r.q)||r.q.length<5||!r.q.every(Number.isFinite)||!Number.isFinite(r.time_start)||!Number.isFinite(r.time_end)||!Number.isInteger(r.frames)||r.frames<2||r.time_end<=r.time_start)throw new Error('計算摘要不足以產生可靠的共同範圍，請查看各配方的結果。');
 }
 const range={q_min:Math.max(...summaries.map(r=>Math.min(...r.q))),q_max:Math.min(...summaries.map(r=>Math.max(...r.q))),time_start:Math.max(...summaries.map(r=>r.time_start)),time_end:Math.min(...summaries.map(r=>r.time_end))};
 if(range.q_min>=range.q_max||range.time_start>=range.time_end)throw new Error('五份結果沒有足夠的共同 q 或時間範圍，請人工確認來源。');
 const frameCounts=summaries.map(r=>{
  const dt=(r.time_end-r.time_start)/(r.frames-1),a=(range.time_start-r.time_start)/dt,b=(range.time_end-r.time_start)/dt;
  if(Math.abs(a-Math.round(a))>1e-7||Math.abs(b-Math.round(b))>1e-7)throw new Error('共同時間端點未對齊每份資料的時間步，請人工選擇時間窗。');
  if(r.q.filter(q=>q>=range.q_min&&q<=range.q_max).length<5)throw new Error('共同 q 範圍內有配方不足五個 q 點，無法直接套用。');
  return Math.round(b)-Math.round(a)+1;
 });
 return {extractionId:rawExtraction.id,range,minFrames:Math.min(...frameCounts),maxBlocks:Math.min(10,Math.floor(Math.min(...frameCounts)/2))};
}
$('suggestQualityRange').onclick=()=>{
 try{
  clearError();qualityRangeProposal=qualityRangeFromExtraction();
  const p=qualityRangeProposal,r=p.range;
  $('qualityRangeHint').textContent=`共同 q 範圍：${r.q_min}–${r.q_max}；共同時間範圍：${r.time_start}–${r.time_end}。每份至少 ${p.minFrames} 個 frame。${p.maxBlocks>=2?'分段數可填 2–'+p.maxBlocks+'。':'frame 不足以分成兩段。'} 按「套用建議範圍」帶入 q 與時間端點；門檻與分段數維持原值。`;
 }catch(e){qualityRangeProposal=null;$('qualityRangeHint').textContent=e.message;error(e,false)}
};
$('applyQualityRange').onclick=()=>{
 try{
  if(!qualityRangeProposal||qualityRangeProposal.extractionId!==rawExtraction?.id)throw new Error('請先按「從計算結果取得範圍建議」，查看本次結果後再套用。');
  const p=qualityRangeFromExtraction();
  if(p.maxBlocks<2)throw new Error('共同時間窗不足以做至少兩段檢查，未套用設定。');
  for(const [key,value] of Object.entries(p.range))$(key).value=String(value);
  invalidate();clearError();
  const blocks=Number($('blocks').value);
  $('qualityRangeHint').textContent=`已帶入共同 q 與時間範圍，請重新檢查 q*。${!Number.isInteger(blocks)||blocks<2||blocks>p.maxBlocks?' 目前分段數不適用，請填入 2–'+p.maxBlocks+' 的整數。':''}`;
  qualityRangeProposal=null;
 }catch(e){error(e,false)}
};
function invalidateRaw(){clearQualityRange();drivePlan=null;rawExtraction=null;$('scatterResults').innerHTML='';$('rawResults').innerHTML='';$('rawProgress').textContent='raw 來源或計算設定已變更，請重新預覽／計算。';invalidate();}
function applyRawUnits(){const s=collectRaw();$('q_unit').value=s.length_unit+'^-1';$('time_unit').value=s.time_unit;$('time_origin').value=`time = step × ${s.time_scale} + ${s.time_offset}`;$('structure_definition').value=`Binary composition Scc = |cB*rhoA-cA*rhoB|²/N; rhoX=sum_X exp(i k.r); cX=NX/N from actual particles. ${s.normalization==='scc_normalized'?'Divide by cA*cB.':'Unnormalized Scc.'} Type A=${s.type_a}, B=${s.type_b}; periodic orthorhombic box; all reciprocal vectors through qmax=${s.q_max}, radial bins dq=${s.dq}. Not SAXS intensity.`;invalidate();}
async function chooseFolder(i){try{const result=await runJob('choose_folder',{});if(result.path){document.querySelector(`[data-row="${i}"][data-key="path"]`).value=result.path;$('pathNote'+i).classList.add('hidden');invalidateRaw();}}catch(e){error(e)}}
function renderRaw(result,complete){
 $('rawResults').innerHTML=result.results.map((value,i)=>{const r=complete?value.summary:value;return `<article class="quality-card"><h3>配方 ${i+1} · ${r.frames} frames</h3><p class="sub">${r.counts?`實際粒子 A:B = ${r.counts[0]}:${r.counts[1]} · A 占比 ${r.particle_fraction_a.toPrecision(5)}`:'A:B 粒子數將於完整座標讀取後驗證'}<br>原始步數 ${r.first_step}–${r.last_step} → 時間 ${r.time_start}–${r.time_end}<br>${r.q.length} 個 q 分箱 · ${r.modes_half} 個獨立方向向量 · 計算量約 ${r.estimated_particle_mode_pairs.toLocaleString()} 粒子–向量組合<br>可用 q 範圍 ${r.q[0].toPrecision(6)}–${r.q.at(-1).toPrecision(6)}</p>${complete?`<div class="notice green">S(q,t) 已保存；重用 ${value.cache_hits} 個 frame 的計算快取。<div style="overflow-wrap:anywhere">${esc(value.csv)}</div></div>`:''}<details><summary>查看 q 網格與各箱方向數</summary><pre>${esc(JSON.stringify({q:r.q,q_low:r.q_low,q_high:r.q_high,directions:r.directions_full},null,2))}</pre></details></article>`}).join('');
 if(result.source_mode==='drive'){
 const note=document.createElement('div');note.className='notice green';
 note.textContent=complete?`本次工作 API 回應資料量：${mib(result.transfer_bytes)} MiB。原始座標未另存；曲線、部分相關項與來源紀錄已保存。`:`尚需讀取原始座標約 ${mib(result.remaining_raw_bytes)} MiB（另有清單／版本查核流量）；預估曲線及快取約 ${mib(result.estimated_output_and_cache_bytes)} MiB。本次預覽 API 回應資料量 ${mib(result.transfer_bytes)} MiB。確認後再按計算。`;
 $('rawResults').prepend(note);
 }
 if(complete){$('rawProgress').textContent=(isLowQ()?'五份 S(q,t) 已完成。下一步：低 q 資料檢查。':isM()?'五份 S(q,t) 已完成。下一步：M 資料檢查。':'五份 S(q,t) 已完成。下一步：q* 品質檢查。');}else{$('rawProgress').textContent='預覽完成；請確認取樣與計算量，再按「計算五份 S(q,t)」。'}
}
async function rawAction(kind){try{const plan=drivePlan;invalidateRaw();const payload={settings:collectRaw(),folders:Array.from({length:5},(_,i)=>rowValue(i,'path')),source_mode:$('source_mode').value,drive_options:collectDrive(),plan_id:plan?.id};if(payload.source_mode==='drive'&&kind==='extract_raw'&&!plan)throw new Error('請先預覽 Drive 資料夾與傳輸量，再按計算。');const result=await runJob(kind,payload);if(kind==='extract_raw')rawExtraction=result;else if(payload.source_mode==='drive')drivePlan=result;renderRaw(result,kind==='extract_raw');}catch(e){$('rawProgress').textContent=e.message;error(e)}}
function collectProfiles(){return ['SANS','SAXS'].filter(k=>$(k.toLowerCase()+'_enabled').checked).map(technique=>{const p={technique};for(const k of ['mode','amplitude_unit','mapping_note','sample_note','table'])p[k]=$(technique.toLowerCase()+'_'+k).value;for(const k of ['b_a','b_b']){const v=$(technique.toLowerCase()+'_'+k).value;p[k]=v===''?null:Number(v)}return p})}
function fillProfiles(project){for(const kind of ['SANS','SAXS']){const p=(project.experiment_profiles||[]).find(p=>p.technique===kind),prefix=kind.toLowerCase()+'_';$(prefix+'enabled').checked=!!p;for(const k of ['mode','amplitude_unit','mapping_note','sample_note','table','b_a','b_b'])$(prefix+k).value=p?.[k]??(k==='mode'?'constant':'')}$('scatter_start').value=project.experiment_window?.start??'';$('scatter_end').value=project.experiment_window?.end??'';$('scatterResults').innerHTML='';}
$('scatteringPanel').querySelectorAll('input,select,textarea').forEach(e=>e.addEventListener('input',()=>{$('scatterResults').innerHTML='<p class="hint">對照設定已變更，請重新產生曲線。</p>'}));
$('projectScattering').onclick=async()=>{try{if(!rawExtraction)throw new Error('請先完成 raw data 計算。');$('scatterResults').innerHTML='正在重組部分相關項…';const start=$('scatter_start').value,end=$('scatter_end').value;const r=await runJob('project_scattering',{extraction_id:rawExtraction.id,profiles:collectProfiles(),window:{start:start===''?null:Number(start),end:end===''?null:Number(end)}});$('scatterResults').innerHTML='<div class="notice">已保存獨立加權曲線；尚未與實驗驗證。以下縱軸為 S_weighted，不會更改目前選擇的 GP target。</div>'+r.curves.map(c=>`<article class="quality-card"><h3>${esc(c.label)}</h3>${chart(c)}<p class="hint" style="overflow-wrap:anywhere">${esc(c.path)}</p></article>`).join('');}catch(e){$('scatterResults').textContent=e.message;error(e)}};
$('source_mode').onchange=()=>{sourceMode();invalidateRaw()};
for(const k of [...rawNumeric,...rawText])$('raw_'+k).addEventListener('input',invalidateRaw);
$('applyRawUnits').onclick=applyRawUnits;$('previewRaw').onclick=()=>rawAction('preview_raw');$('extractRaw').onclick=()=>rawAction('extract_raw');
$('cancelRaw').onclick=async()=>{if(!rawJobId)return;try{const r=await api('/api/cancel',{job_id:rawJobId});$('rawProgress').textContent=r.message;$('cancelRaw').disabled=true}catch(e){error(e)}};
$('refreshHistory').onclick=history;document.querySelectorAll('[data-project]').forEach(e=>e.addEventListener('input',invalidate));renderRows(Array.from({length:5},()=>({label:'',ratio:'',seed_id:'',path:''})));gate();history();
$('ratio_encoding').addEventListener('change',()=>{updateRatios();invalidate()});

$('rawDemo').onclick=async()=>{clearError();setBusy(true,'準備合成位置檔…');try{fill(await api('/api/raw-demo',{}));page(0)}catch(e){error(e)}finally{setBusy(false,'raw 合成示範已載入；請預覽並計算，所有數值僅供流程驗證。')}};

function collectDrive(){return Object.fromEntries(driveFields.map(k=>[k,Number($('drive_'+k).value)]));}
function mib(bytes){return (Number(bytes||0)/1048576).toFixed(2);}
function showDriveStatus(s){$('driveAuthStatus').textContent=s.connected?'已登入 Google Drive。可以預覽指定的資料夾。':s.pending?'登入尚未完成。請開啟 Google 登入連結，完成後更新狀態。':'尚未登入。請先完成一次性 OAuth 設定。';}
$('driveLogin').onclick=async()=>{clearError();setBusy(true,'準備登入連結…');try{$('driveLoginLink').classList.add('hidden');const r=await api('/api/drive/login',{client_json_path:$('driveClientPath').value,consent:$('driveConsent').checked});$('driveLoginLink').href=r.url;$('driveLoginLink').classList.remove('hidden');$('driveAuthStatus').textContent='請親自點擊「開啟 Google 登入」。完成後回來按「更新登入狀態」。';}catch(e){error(e)}finally{setBusy(false,'登入連結設定結束。')}};
$('driveStatus').onclick=async()=>{try{showDriveStatus(await api('/api/drive/status'));}catch(e){error(e)}};
$('driveDisconnect').onclick=async()=>{clearError();setBusy(true,'清除本次登入…');try{showDriveStatus(await api('/api/drive/disconnect',{}));$('driveLoginLink').removeAttribute('href');$('driveLoginLink').classList.add('hidden');drivePlan=null;}catch(e){error(e)}finally{setBusy(false,'登入狀態已更新。')}};
driveFields.forEach(k=>$('drive_'+k).addEventListener('input',invalidateRaw));

initTargetUI();

for(const k of Object.keys(kernelLabels))$('kernel_'+k).addEventListener('change',()=>{ $('reviewed').checked=false; updateKernelSummary(); });
updateKernelSummary();
