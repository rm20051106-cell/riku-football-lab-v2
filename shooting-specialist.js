(function(){
'use strict';
const PANEL_ID='rikuShootingSpecialistPanel';
const UNKNOWN='映像で確認できない';
const definitions=[
 {id:'approachRhythm',label:'助走のリズム',options:[UNKNOWN,'毎回ほぼ一定','加速が自然','歩幅がばらつく','最後に詰まる','最後に伸びすぎる']},
 {id:'approachAngle',label:'助走の角度',options:[UNKNOWN,'狙う方向に対して自然','正面から入る','斜めから入る','角度が毎回違う']},
 {id:'plantPosition',label:'軸足の位置',options:[UNKNOWN,'ボールの横','ボールに近すぎる','ボールから遠すぎる','ボールより前','ボールより後ろ']},
 {id:'plantDirection',label:'軸足のつま先の向き',options:[UNKNOWN,'狙う方向','内側を向く','外側を向く','狙いと別方向']},
 {id:'swing',label:'蹴り足の振り',options:[UNKNOWN,'スムーズに振れている','振りが小さい','振りが大きく不安定','途中で止まる','振り抜き方向がずれる']},
 {id:'impact',label:'インパクト・当たり方',options:[UNKNOWN,'足の甲で捉えた','インサイドで捉えた','アウトサイドで捉えた','つま先に当たった','芯を外した','接触の瞬間が画面外']},
 {id:'trunk',label:'体幹・上体',options:[UNKNOWN,'前傾が保てている','上体が反り気味','前に倒れすぎる','左右に傾く','上体が開きすぎる']},
 {id:'balance',label:'蹴った後のバランス',options:[UNKNOWN,'自然に前へ流れる','安定して立てる','前に崩れる','横に流れる','後ろに残る','着地が不安定']},
 {id:'target',label:'狙ったコース',options:[UNKNOWN,'左上','左下','中央上','中央下','右上','右下','ニアサイド','ファーサイド','ゴール前へ合わせる','味方のいるスペース']},
 {id:'result',label:'キックの結果',options:[UNKNOWN,'ゴール','枠内・GKに止められた','枠内・DFにブロック','枠外','味方に届いた','相手に渡った','壁に当たった']}
];
const extra=[
 {id:'shotType',label:'キックの種類',options:['インステップ','インサイド','カーブ','無回転','ボレー','ロングキック','直接FK','間接FK','クロス・合わせるキック','その他']},
 {id:'distance',label:'カメラからの距離',options:['近距離','中距離','遠距離','未確認']},
 {id:'framing',label:'映像の写り方',options:['全身とボールが見える','足元とボールが見える','上半身中心','足元が隠れる','ボールが隠れる','その他']}
];
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function getState(){if(typeof state==='undefined')return null;state.shootingSpecialistRecords=Array.isArray(state.shootingSpecialistRecords)?state.shootingSpecialistRecords:[];return state;}
function readFormMeta(){return {title:(document.getElementById('formTitle')||{}).value||'',kind:(document.getElementById('formKind')||{}).value||'シュート',foot:(document.getElementById('formFoot')||{}).value||'右足',cameraAngle:(document.getElementById('formCameraAngle')||{}).value||'未選択'};}
function mount(){
 const form=document.getElementById('form'),checks=document.getElementById('formChecks');
 if(!form||!checks||document.getElementById(PANEL_ID))return;
 const panel=document.createElement('div');panel.className='card';panel.id=PANEL_ID;
 panel.innerHTML='<h2>専門分析｜助走・軸足・インパクト・狙い</h2>'+
 '<p class="tiny muted">動画を一時停止し、見えた内容だけ選択してください。見えない項目は「映像で確認できない」のままで保存できます。既存のフォーム動画・基本チェック表はそのまま使います。</p>'+
 '<div class="two"><label class="label">カメラからの距離<select data-ss-extra="distance">'+extra[1].options.map(function(x){return '<option>'+esc(x)+'</option>';}).join('')+'</select></label><label class="label">映像の写り方<select data-ss-extra="framing">'+extra[2].options.map(function(x){return '<option>'+esc(x)+'</option>';}).join('')+'</select></label></div>'+
 '<label class="label">キックの種類<select data-ss-extra="shotType">'+extra[0].options.map(function(x){return '<option>'+esc(x)+'</option>';}).join('')+'</select></label>'+
 '<div class="two">'+definitions.map(function(f){return '<label class="label">'+esc(f.label)+'<select data-ss-field="'+f.id+'">'+f.options.map(function(x){return '<option>'+esc(x)+'</option>';}).join('')+'</select></label>';}).join('')+'</div>'+
 '<label class="label">専門分析メモ（任意）<textarea data-ss-note maxlength="300" placeholder="例：横から撮影。軸足の位置は見えたが、ボールとの接触は足で隠れていた。"></textarea></label>'+
 '<div class="btnrow"><button type="button" id="ssSave">専門分析を保存</button><button type="button" class="secondary" id="ssReset">入力をリセット</button></div>'+
 '<div id="ssStatus" class="tiny muted" style="margin-top:8px"></div>'+
 '<div class="divider"></div><h3>同じ条件での比較</h3><div id="ssComparison" class="tiny muted">同じ条件の記録が3件以上集まると傾向を表示します。</div>'+
 '<div class="divider"></div><h3>陸玖専用・改善練習候補</h3><div id="ssPractice" class="tiny muted">記録が集まるまではフォームの弱点を決めつけません。</div>'+
 '<div class="divider"></div><h3>専門分析の記録</h3><div id="ssRecords"></div>';
 checks.insertAdjacentElement('afterend',panel);
 document.getElementById('ssSave').addEventListener('click',saveRecord);
 document.getElementById('ssReset').addEventListener('click',function(){panel.querySelectorAll('[data-ss-field],[data-ss-extra]').forEach(function(el){el.selectedIndex=0;});panel.querySelector('[data-ss-note]').value='';});
}
function currentSetup(){
 const m=readFormMeta(),p=document.getElementById(PANEL_ID);
 return {kind:m.kind,foot:m.foot,cameraAngle:m.cameraAngle,distance:p.querySelector('[data-ss-extra="distance"]').value,framing:p.querySelector('[data-ss-extra="framing"]').value,shotType:p.querySelector('[data-ss-extra="shotType"]').value};
}
function setupKey(x){return [x.kind,x.foot,x.cameraAngle,x.distance,x.framing,x.shotType].join('|');}
function saveRecord(){
 const s=getState(),p=document.getElementById(PANEL_ID);if(!s||!p)return;
 const m=readFormMeta();if(!m.title.trim()){alert('先にフォーム動画のタイトルを入力してください。');return;}
 const source=(s.forms||[]).find(function(x){return String(x.title||'')===String(m.title.trim())&&x.kind===m.kind&&x.foot===m.foot&&(!x.cameraAngle||x.cameraAngle===m.cameraAngle);});
 if(!source){alert('先に「フォーム分析を保存」で、この動画を保存してください。その後、同じ動画の専門分析を保存できます。');return;}
 const fields={};definitions.forEach(function(f){fields[f.id]=p.querySelector('[data-ss-field="'+f.id+'"]').value;});
 const setup=currentSetup();
 const record={id:Date.now(),date:typeof today==='function'?today():new Date().toISOString().slice(0,10),title:m.title.trim(),kind:m.kind,foot:m.foot,cameraAngle:m.cameraAngle,setup:setup,fields:fields,note:p.querySelector('[data-ss-note]').value.trim().slice(0,300),sourceFormId:source.id,reviewedAt:new Date().toISOString()};
 s.shootingSpecialistRecords.unshift(record);
 if(typeof persist==='function')persist();
 render();
 const status=document.getElementById('ssStatus');if(status)status.textContent='保存しました。動画記録「'+record.title+'」に紐づけました。';
 alert('シュート・フリーキック専門分析を保存しました。');
}
function sameSetupRows(records,latest){
 const key=setupKey(latest.setup||latest);
 return records.filter(function(x){return setupKey(x.setup||x)===key;});
}
function summarize(rows){
 const counts={};definitions.forEach(function(f){const values={};rows.forEach(function(r){const v=(r.fields||{})[f.id];if(v&&v!==UNKNOWN)values[v]=(values[v]||0)+1;});counts[f.id]=values;});
 return counts;
}
function recommendations(rows,counts){
 const ideas=[];
 function repeated(id,choices,title,drill){const found=choices.map(function(v){return {value:v,count:counts[id][v]||0};}).sort(function(a,b){return b.count-a.count;})[0];if(found&&found.count>=2)ideas.push({count:found.count,title:title,drill:drill,reason:'同じ撮影条件の記録で「'+found.value+'」が'+found.count+'回確認されています。'});}
 repeated('approachRhythm',['歩幅がばらつく','最後に詰まる','最後に伸びすぎる','角度が毎回違う'],'助走の再現性を整える','ボールを置き、助走の開始位置と歩数を決めて、力を抑えた助走を左右各4回。最後の一歩を毎回同じリズムにする。');
 repeated('plantPosition',['ボールに近すぎる','ボールから遠すぎる','ボールより前','ボールより後ろ'],'軸足の位置を安定させる','ボール横に目印を置き、ゆっくりした助走で軸足を置く練習を6回。強く蹴らず、位置を先にそろえる。');
 repeated('plantDirection',['内側を向く','外側を向く','狙いと別方向'],'軸足の向きと狙いをそろえる','左右に目標を置き、蹴る前に軸足のつま先と目標方向を確認して軽く蹴る練習を各4回。');
 repeated('swing',['振りが小さい','振りが大きく不安定','途中で止まる','振り抜き方向がずれる'],'蹴り足の振り抜きを整える','近距離でボールを軽く蹴り、助走から振り抜きまでを一定のテンポで5回。強さより滑らかな動きを優先。');
 repeated('trunk',['上体が反り気味','前に倒れすぎる','左右に傾く','上体が開きすぎる'],'体幹と上体の安定を確認する','ボールなしのゆっくりしたキック動作を5回。胸と骨盤の向きを確認し、無理に反らず自然な姿勢を保つ。');
 repeated('balance',['前に崩れる','横に流れる','後ろに残る','着地が不安定'],'蹴った後の着地とバランスを整える','力を抑えたキックを5回。蹴った後に2秒静止し、片足で無理なく立てる範囲でバランスを確認。');
 return ideas;
}
function render(){
 const s=getState(),p=document.getElementById(PANEL_ID);if(!s||!p)return;
 const records=s.shootingSpecialistRecords||[];
 const list=p.querySelector('#ssRecords'),compare=p.querySelector('#ssComparison'),practice=p.querySelector('#ssPractice');
 if(!records.length){list.innerHTML='<div class="tiny muted">まだ専門分析の記録はありません。</div>';compare.textContent='同じ条件の記録が3件以上集まると傾向を表示します。';practice.textContent='まずは動画を保存し、見える項目だけ記録してください。';return;}
 list.innerHTML=records.slice(0,10).map(function(r){const known=definitions.filter(function(f){return r.fields&&r.fields[f.id]&&r.fields[f.id]!==UNKNOWN;}).length;const form=(s.forms||[]).find(function(x){return String(x.id)===String(r.sourceFormId);});return '<div class="listitem"><div class="grow"><b>'+esc(r.date)+'｜'+esc(r.title)+'（'+esc(r.kind)+'）</b><div class="tiny muted">'+esc(r.cameraAngle)+'・'+esc(r.setup.distance)+'・'+esc(r.setup.shotType)+'・確認 '+known+'/'+definitions.length+'項目</div><div class="tiny">'+esc((r.fields||{}).approachRhythm||UNKNOWN)+'／軸足 '+esc((r.fields||{}).plantPosition||UNKNOWN)+'／結果 '+esc((r.fields||{}).result||UNKNOWN)+'</div>'+(r.note?'<div class="tiny muted">'+esc(r.note)+'</div>':'')+(form&&form.hasVideo?'<button type="button" class="secondary small" data-ss-play="'+esc(r.sourceFormId)+'">元動画を再生</button>':'<div class="tiny muted">元動画の再生リンクはありません。</div>')+'</div><button type="button" class="danger small" data-ss-delete="'+r.id+'">削除</button></div>';}).join('');
 list.querySelectorAll('[data-ss-delete]').forEach(function(btn){btn.addEventListener('click',function(){if(!confirm('この専門分析記録を削除しますか？'))return;s.shootingSpecialistRecords=s.shootingSpecialistRecords.filter(function(x){return String(x.id)!==btn.getAttribute('data-ss-delete');});if(typeof persist==='function')persist();render();});});
 list.querySelectorAll('[data-ss-play]').forEach(function(btn){btn.addEventListener('click',function(){if(typeof playSavedForm==='function')playSavedForm(Number(btn.getAttribute('data-ss-play')));});});
 const latest=records[0],rows=sameSetupRows(records,latest);
 const setup=latest.setup||latest;
 const setupText=[setup.kind,setup.foot,setup.cameraAngle,setup.distance,setup.framing,setup.shotType].join('｜');
 if(rows.length<3){compare.innerHTML='<div class="tiny muted">比較条件：'+esc(setupText)+'</div><div class="note">評価保留：同じ条件の記録は'+rows.length+'件です。3件以上集まるまで傾向を断定しません。</div>';practice.innerHTML='<div class="note">改善テーマは評価保留です。まず同じ条件であと'+(3-rows.length)+'件記録してください。</div>';return;}
 const counts=summarize(rows);
 const rowsHtml=definitions.map(function(f){const items=Object.entries(counts[f.id]).sort(function(a,b){return b[1]-a[1];});return '<div class="tiny"><b>'+esc(f.label)+'</b>：'+(items.length?items.map(function(x){return esc(x[0])+' '+x[1]+'回';}).join('／'):'確認できる記録なし')+'</div>';}).join('');
 const knownOutcomes=rows.filter(function(r){const v=r.fields&&r.fields.result;return v&&v!==UNKNOWN;});
 const goals=knownOutcomes.filter(function(r){return r.fields.result==='ゴール';}).length;
 compare.innerHTML='<div class="tiny muted">比較条件：'+esc(setupText)+'｜同条件 '+rows.length+'件</div><div class="tiny muted">映像で確認できた選択内容の集計です。フォームの良否や成功率を自動判定するものではありません。</div>'+rowsHtml+'<div class="tiny" style="margin-top:6px">結果が確認できた記録：'+knownOutcomes.length+'件／ゴール '+goals+'件。結果不明は集計から除外。</div>';
 const ideas=recommendations(rows,counts);
 if(!ideas.length){practice.innerHTML='<div class="note">同じ条件の記録では、繰り返し現れる改善項目はまだ確認できません。今のフォームを再現しながら記録を続けましょう。</div>';return;}
 ideas.sort(function(a,b){return b.count-a.count;});
 practice.innerHTML=ideas.slice(0,2).map(function(x){return '<div class="note"><b>'+esc(x.title)+'</b><div class="tiny">'+esc(x.reason)+'</div><div class="tiny"><b>練習：</b>'+esc(x.drill)+'</div><button type="button" class="secondary small" data-ss-plan="'+esc(x.title)+'" data-ss-drill="'+esc(x.drill)+'">この練習を今日のメニューに設定</button></div>';}).join('');
 practice.querySelectorAll('[data-ss-plan]').forEach(function(btn){btn.addEventListener('click',function(){const name=btn.getAttribute('data-ss-plan'),drill=btn.getAttribute('data-ss-drill');if(typeof state==='undefined')return;const category=latest.kind==='フリーキック'?'キック':'シュート';const menu={name:name,category:category,minutes:10};state.menus=Array.isArray(state.menus)?state.menus:[];if(!state.menus.some(function(x){return x.name===name;}))state.menus.unshift(menu);if(typeof persist==='function')persist();const sel=document.getElementById('trainMenu');if(sel)sel.value=name;const focus=document.getElementById('trainFocus');if(focus)focus.value='シュート';const note=document.getElementById('trainNote');if(note)note.value=drill;if(typeof showView==='function')showView('training');});});
}
function install(){
 if(typeof state==='undefined')return;
 mount();render();
 const kind=document.getElementById('formKind');if(kind&&!kind.__ssBound){kind.__ssBound=true;kind.addEventListener('change',function(){const p=document.getElementById(PANEL_ID);if(p){p.querySelectorAll('[data-ss-field],[data-ss-extra]').forEach(function(x){x.selectedIndex=0;});render();}});}
 if(typeof window.renderAll==='function'&&!window.renderAll.__shootingSpecialistWrapped){const original=window.renderAll;const wrapped=function(){const result=original.apply(this,arguments);render();return result;};wrapped.__shootingSpecialistWrapped=true;window.renderAll=wrapped;}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
window.renderRikuShootingSpecialist=render;
})();