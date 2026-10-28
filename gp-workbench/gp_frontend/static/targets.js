'use strict';
const mNumeric=['time_start','time_end','q_min','q_max','blocks'];
function isM(){return document.getElementById('target_kind').value==='composition_strength'}
function isLowQ(){return document.getElementById('target_kind').value==='low_q_shell_mean'}
function targetLabel(kind){return kind==='low_q_shell_mean'?'低 q 平均':kind==='composition_strength'?'M':'q*'}
function collectLowQ(){return Object.fromEntries(mNumeric.map(k=>[k,$('low_'+k).value.trim()===''?null:Number($('low_'+k).value)]))}
function collectM(){return Object.fromEntries(mNumeric.map(k=>[k,$('m_'+k).value.trim()===''?null:Number($('m_'+k).value)]))}
let originalTargetText=null;
function updateTargetUI(){
 const m=isM(),low=isLowQ();
 $('qTargetSettings').classList.toggle('hidden',m||low);$('mTargetSettings').classList.toggle('hidden',!m);$('lowTargetSettings').classList.toggle('hidden',!low);
 const swaps=[
  [$('navQualityLabel'),'M 資料檢查'],
  [$('activeTargetTitle'),'第一階段 / ratio → M'],
  [document.querySelector('#page0 > .lead'),'填入五個配方，匯入 S(q,t) 或從 raw 計算。'],
  [document.querySelector('#page1 > h1'),'M 資料檢查'],
  [document.querySelector('#page1 > .lead'),'設定時間窗與頻帶，檢查五個配方。'],
  [document.querySelector('#page1 .panel h2'),'提取設定'],
  [document.querySelector('#page0 [data-nav="1"]'),'下一步：M 資料檢查'],
  [$('nextQualityRaw'),'接著設定 M 頻帶與資料檢查'],
  [$('scatterTargetNote'),'用 AA、BB、AB 部分相關項與散射權重，產生 SANS／SAXS 對照曲線。']
 ];
 if(!originalTargetText)originalTargetText=swaps.map(([e])=>e.textContent);
 const lowTexts=['低 q 資料檢查','第一階段 / ratio → 低 q 平均','填入五個配方，匯入 S(q,t) 或從 raw 計算。','低 q 資料檢查','設定時間窗與頻帶，檢查五個配方。','提取設定','下一步：低 q 資料檢查','接著設定低 q 頻帶與資料檢查','用 AA、BB、AB 部分相關項與散射權重，產生 SANS／SAXS 對照曲線。'];
 swaps.forEach(([e,text],i)=>{if(low)e.textContent=lowTexts[i];else if(m)e.textContent=text;else e.textContent=originalTargetText[i]});
 $('targetHelp').textContent=m?'M：按方向數加權的頻帶組成起伏超額，物理下限為 −1。':'q*：時間平均結構因子主峰的波數，對應特徵尺度約為 2π/q*。';
 $('analyze').textContent=m?'計算 M 並檢查五個配方':'檢查五個配方';
 if(!analysis){$('qualityResults').className='empty';$('qualityResults').textContent=m?'檢查後顯示 M、平均曲線與分段差距。':'檢查後顯示平均曲線與峰位。'}
 if(low){$('targetHelp').textContent='低 q 平均：固定頻帶內正規化濃度結構因子的完整 shell 等權平均。';$('analyze').textContent='計算低 q 平均並檢查五個配方';if(!analysis)$('qualityResults').textContent='檢查後顯示低 q 平均、shell 與分段差距。'}
 refreshProbeTargets();updateWindowControls();
 gate();
}
function renderLowQQuality(a){
 $('qualityCount').textContent=a.results.filter(r=>r.status==='ready').length+' / 5 可計算低 q 平均';$('qualityResults').className='';
 $('qualityResults').innerHTML=a.results.map(r=>`<article class="quality-card"><div class="quality-head"><h3>${esc(r.label)} · ratio ${esc(r.ratio)} · seed ${esc(r.seed_id)}</h3><span class="tag ${r.status==='ready'?'':'warn'}">${r.status==='ready'?'低 q 資料完整':'需要確認'}</span></div>${r.low_q_value!==undefined?`<div class="mini">低 q 平均 = ${r.low_q_value.toPrecision(7)}</div><p class="sub">${r.n_frames} frames · 頻帶 ${r.band.join('–')} · ${r.shell_count} 個完整 shell（等權） · 實際 q ${r.actual_q_range.map(v=>v.toPrecision(7)).join('–')}</p>${chart({...r,q_peak:null})}<div class="chart-note">${r.blocks.map((b,i)=>`<span><span class="legend-line" style="background:${colors[i]}"></span>${b.time_start}–${b.time_end}：${b.low_q_value.toPrecision(7)}</span>`).join('')}</div><p>全窗口與分段最大差距：${r.low_q_spread.toPrecision(4)}；相對差距：${r.low_q_relative_spread===null?'平均接近零，不顯示百分比':(100*r.low_q_relative_spread).toPrecision(4)+'%'}</p><details><summary>查看各 shell 平均、權重與來源</summary><pre>${esc(JSON.stringify({version:r.definition_version,band:r.band,q:r.q,mean:r.mean,shell_weights:r.shell_weights,directions_full:r.directions_full,sha256:r.sha256,manifest_sha256:r.manifest_sha256,path:r.path,note:r.note},null,2))}</pre></details>`:''}${r.reasons.length?`<div class="notice">${r.reasons.map(esc).join('<br>')}</div>`:''}</article>`).join('');gate();
}
function renderMQuality(a){
 $('qualityCount').textContent=a.results.filter(r=>r.status==='ready').length+' / 5 可計算 M';$('qualityResults').className='';
 $('qualityResults').innerHTML=a.results.map(r=>`<article class="quality-card"><div class="quality-head"><h3>${esc(r.label)} · ratio ${esc(r.ratio)} · seed ${esc(r.seed_id)}</h3><span class="tag ${r.status==='ready'?'':'warn'}">${r.status==='ready'?'M 資料完整':'需要確認'}</span></div>${r.m_value!==undefined?`<div class="mini">M = ${r.m_value.toPrecision(7)}</div><p class="sub">${r.n_frames} frames · 頻帶 ${r.band.join('–')} · 實際波向量範圍 ${r.actual_q_range.map(v=>v.toPrecision(7)).join('–')} · ${r.mode_count} 個正負方向（不是獨立樣本數）</p>${chart({...r,q_peak:null})}<div class="chart-note">${r.blocks.map((b,i)=>`<span><span class="legend-line" style="background:${colors[i]}"></span>${b.time_start}–${b.time_end}：M = ${b.m_value.toPrecision(7)}</span>`).join('')}</div><p>全窗口與分段最大差距：${r.m_spread.toPrecision(4)}；相對差距：${r.m_relative_spread===null?'M 接近零，不顯示百分比':(100*r.m_relative_spread).toPrecision(4)+'%'}</p><details><summary>查看 M 權重與來源紀錄</summary><pre>${esc(JSON.stringify({band:r.band,q:r.q,directions_full:r.directions_full,sha256:r.sha256,manifest_sha256:r.manifest_sha256,path:r.path,note:r.note},null,2))}</pre></details>`:''}${r.reasons.length?`<div class="notice">${r.reasons.map(esc).join('<br>')}</div>`:''}</article>`).join('');gate();
}
function initTargetUI(){
 $('target_kind').onchange=()=>{invalidate();clearError();updateTargetUI()};
 mNumeric.forEach(k=>$('m_'+k).addEventListener('input',invalidate));
 mNumeric.forEach(k=>$('low_'+k).addEventListener('input',invalidate));
 $('qUseDataWindow').onclick=()=>applyCommonTimeWindow('');
 $('lowUseRawWindow').onclick=()=>applyCommonTimeWindow('low_');
 $('mUseRawWindow').onclick=()=>applyCommonTimeWindow('m_');
 updateTargetUI();
}
