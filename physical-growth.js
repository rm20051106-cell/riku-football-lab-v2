(function(){
'use strict';
const ID='rikuPhysicalGrowthPanel';
const TYPES=['30m走','アジリティ','立ち幅跳び','100m走'];
const META=[
{id:'surface',label:'計測場所・路面',options:['未記録','屋外・土','屋外・天然芝','人工芝','体育館・床','陸上トラック','その他']},
{id:'method',label:'計測方法',options:['未記録','手動ストップウォッチ','光電管・電子計測','アプリ・動画計測','巻尺・メジャー','その他']},
{id:'warmup',label:'計測前の準備',options:['未記録','準備運動あり','準備運動なし','不明']},
{id:'attempts',label:'記録の採用方法',options:['未記録','1回のみ','複数回のベスト','複数回の平均','不明']}
];
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function data(){if(typeof state==='undefined')return null;state.measures=Array.isArray(state.measures)?state.measures:[];return state;}
function mount(){
 const anchor=document.getElementById('measureRecords');if(!anchor||document.getElementById(ID))return;
 const panel=document.createElement('div');panel.className='card';panel.id=ID;
 panel.innerHTML='<h2>フィジカル成長ラボ</h2><p class="tiny muted">測定値を時系列で確認し、同じ種目・単位・計測条件の記録だけを比較します。初期登録値も過去データとして表示しますが、計測条件が未記録のため、新しい条件付き記録とは混ぜて比較しません。</p>'+
 '<h3>今回の計測条件</h3><div class="two">'+META.map(m=>'<label class="label">'+esc(m.label)+'<select data-pg-meta="'+m.id+'">'+m.options.map(x=>'<option>'+esc(x)+'</option>').join('')+'</select></label>').join('')+'</div>'+
 '<label class="label">計測条件の補足（任意）<input id="pgNote" maxlength="160" placeholder="例：同じ場所・同じ靴・十分に休んで計測"></label>'+
 '<div class="tiny muted">条件は次に「測定値を保存」を押した記録に紐づきます。既存記録は書き換えません。</div>'+
 '<div class="divider"></div><h3>成長の推移</h3><div id="pgTrends"></div>'+
 '<div class="divider"></div><h3>陸玖のサッカーに活かす練習</h3><div id="pgPractice"></div>'+
 '<div class="divider"></div><h3>測定データの見方</h3><div id="pgNotes" class="tiny muted"></div>';
 anchor.parentElement.insertAdjacentElement('afterend',panel);
}
function metaNow(){const p=document.getElementById(ID),o={};META.forEach(m=>o[m.id]=p.querySelector('[data-pg-meta="'+m.id+'"]').value);o.note=p.querySelector('#pgNote').value.trim().slice(0,160);return o;}
function sameCondition(a,b){return a.type===b.type&&a.unit===b.unit&&JSON.stringify(a.physicalConditions||null)===JSON.stringify(b.physicalConditions||null);}
function direction(type){return /走$|アジリティ/.test(type)?-1:/立ち幅跳び/.test(type)?1:0;}
function fmt(n){return Number(n).toLocaleString('ja-JP',{maximumFractionDigits:2});}
function compareText(type,a,b){
 const d=Number(a.value)-Number(b.value),dir=direction(type);
 const change=(d>0?'+':'')+fmt(d)+' '+(a.unit||'');
 if(Math.abs(d)<0.000001)return '前回と同じ（'+change+'）';
 if(!dir)return '数値差 '+change+'（改善方向は項目の性質により判定しません）';
 return (d*dir>0?'改善方向':'数値は反対方向')+' '+change;
}
function recommendation(rows,type){
 if(rows.length<2)return null;
 const a=rows[0],b=rows[1],d=Number(a.value)-Number(b.value),dir=direction(type);
 if(!dir||Math.abs(d)<0.000001)return null;
 const worsened=d*dir<0;
 if(type==='30m走')return worsened?{title:'加速の最初の数歩を整える',detail:'10m程度の短い加速を4〜5本。1本ごとに十分休み、姿勢を崩さず最初の3歩を力強く。タイムを競うより動きの再現を優先。'}:{title:'加速力を維持する',detail:'短い加速走を3〜4本。毎回同じスタート姿勢と計測方法で記録し、良い動きを再現。'};
 if(type==='アジリティ')return worsened?{title:'減速から切り返す動きを整える',detail:'左右のマーカー間を短く設定。減速→外側の足で踏み替え→再加速を左右各4回。滑らない場所でフォームを優先。'}:{title:'切り返しの質を維持する',detail:'左右交互の短い切り返しを4〜6回。上体を起こしすぎず、次の方向へ素早く出る。'};
 if(type==='立ち幅跳び')return worsened?{title:'ジャンプの踏み切りと着地を整える',detail:'その場の軽いジャンプと着地姿勢を確認してから、立ち幅跳びを3回。膝とつま先の向きをそろえ、静かに着地。'}:{title:'跳ぶ力と着地の安定を維持する',detail:'軽いジャンプ3〜5回と、着地で2秒止まる練習。回数を増やしすぎず、毎回の動作をそろえる。'};
 return null;
}
function render(){
 const s=data(),p=document.getElementById(ID);if(!s||!p)return;
 const records=(s.measures||[]).filter(x=>TYPES.includes(x.type)&&Number.isFinite(Number(x.value))).slice().sort((a,b)=>String(b.date).localeCompare(String(a.date)));
 const groups=TYPES.map(type=>({type,all:records.filter(x=>x.type===type)})).filter(x=>x.all.length);
 const trends=p.querySelector('#pgTrends'),practice=p.querySelector('#pgPractice');
 if(!groups.length){trends.innerHTML='<div class="empty">30m走・アジリティ・立ち幅跳びなどを記録すると推移を表示します。</div>';practice.innerHTML='<div class="empty">測定記録が集まると、同条件での変化をもとに練習を提案します。</div>';return;}
 trends.innerHTML=groups.map(g=>{
  const latest=g.all[0],same=g.all.filter(x=>sameCondition(x,latest)),previous=same[1];
  const known=latest.physicalConditions?META.map(m=>latest.physicalConditions[m.id]||'未記録').join('・'):'計測条件未記録（過去データ）';
  const status=previous?compareText(g.type,latest,previous):'同じ条件の比較対象がまだありません';
  const history=g.all.slice(0,8).map(x=>'<div class="tiny">'+esc(x.date)+'　<b>'+esc(fmt(x.value))+' '+esc(x.unit||'')+'</b>'+(x.physicalConditions?'':' <span class="muted">条件未記録</span>')+'</div>').join('');
  return '<div class="card"><b>'+esc(g.type)+'</b><div class="stat">'+esc(fmt(latest.value))+'<small> '+esc(latest.unit||'')+'</small></div><div class="tiny muted">最新：'+esc(latest.date)+'｜'+esc(known)+'</div><div class="note">'+esc(status)+'</div><div class="tiny muted">同条件の記録 '+same.length+'件（条件が異なる記録は比較対象外）</div><div class="divider"></div>'+history+'</div>';
 }).join('');
 const ideas=[];
 groups.forEach(g=>{const same=g.all.filter(x=>sameCondition(x,g.all[0]));const idea=recommendation(same,g.type);if(idea)ideas.push({...idea,type:g.type,count:same.length});});
 practice.innerHTML=ideas.length?ideas.map(x=>'<div class="note"><b>'+esc(x.type)+'｜'+esc(x.title)+'</b><div class="tiny muted">同条件の測定 '+x.count+'件の変化を参考にした提案</div><div class="tiny">'+esc(x.detail)+'</div><button type="button" class="secondary small" data-pg-plan="'+esc(x.title)+'" data-pg-detail="'+esc(x.detail)+'">今日の練習に設定</button></div>').join(''):'<div class="empty">同じ計測条件で2回以上の記録がそろうと、変化に応じた練習を提案します。測定値だけで能力を断定しません。</div>';
 practice.querySelectorAll('[data-pg-plan]').forEach(b=>b.addEventListener('click',()=>{const name=b.dataset.pgPlan,detail=b.dataset.pgDetail;s.menus=Array.isArray(s.menus)?s.menus:[];if(!s.menus.some(x=>x.name===name))s.menus.unshift({name,category:'アジリティ',minutes:10});if(typeof persist==='function')persist();const menu=document.getElementById('trainMenu');if(menu)menu.value=name;const focus=document.getElementById('trainFocus');if(focus)focus.value='その他';const note=document.getElementById('trainNote');if(note)note.value=detail;if(typeof showView==='function')showView('training');}));
 p.querySelector('#pgNotes').textContent='タイム種目（30m走・100m走・アジリティ）は小さい数値、立ち幅跳びは大きい数値が一般的な改善方向です。ただし、路面・靴・計測機器・準備運動・試行回数が違う場合は単純比較できません。身長や体重、未測定の数値を推測して補いません。';
}
function install(){
 if(typeof state==='undefined')return;mount();
 if(typeof window.saveMeasure==='function'&&!window.saveMeasure.__physicalWrapped){
  const original=window.saveMeasure;
  const wrapped=function(){const before=(state.measures||[]).length;const result=original.apply(this,arguments);if((state.measures||[]).length>before){state.measures[0].physicalConditions=metaNow();if(typeof persist==='function')persist();}return result;};
  wrapped.__physicalWrapped=true;window.saveMeasure=wrapped;
 }
 if(typeof window.renderAll==='function'&&!window.renderAll.__physicalWrapped){
  const original=window.renderAll;const wrapped=function(){const result=original.apply(this,arguments);render();return result;};wrapped.__physicalWrapped=true;window.renderAll=wrapped;
 }
 render();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
window.renderRikuPhysicalGrowth=render;
})();