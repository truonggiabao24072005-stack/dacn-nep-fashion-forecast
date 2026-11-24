document.querySelectorAll('[data-print]').forEach(b=>b.addEventListener('click',()=>window.print()));
document.querySelectorAll('[data-submit-once]').forEach(form=>form.addEventListener('submit',()=>{
  if(!form.checkValidity())return;
  const button=form.querySelector('button[type="submit"],button:not([type])');
  if(button){button.disabled=true;button.textContent='Đang ghi nhận…';}
}));
document.documentElement.classList.add('js');
const current=window.location.pathname;
const navLinks=[...document.querySelectorAll('.sidebar nav>a')];
const catalogSection=['products','variants','categories','brands','sizes','colors'].some(kind=>current.startsWith('/danh-muc/'+kind+'/'));
const activeLink=navLinks.filter(a=>a.pathname===current||(a.pathname!=='/'&&current.startsWith(a.pathname))||(catalogSection&&a.pathname==='/danh-muc/products/')).sort((a,b)=>b.pathname.length-a.pathname.length)[0];
if(activeLink){activeLink.classList.add('active');activeLink.setAttribute('aria-current','page');}
document.querySelectorAll('.tabs>a').forEach(a=>{if(a.pathname===current){a.classList.add('active');a.setAttribute('aria-current','page');}});
const menuToggle=document.querySelector('[data-menu-toggle]'),sideNav=document.getElementById('management-nav'),shell=document.querySelector('.shell'),backdrop=document.querySelector('.nav-backdrop');
if(menuToggle&&sideNav){
  const mobile=window.matchMedia('(max-width:900px)');
  function setMenu(open,returnFocus=true){
    document.body.classList.toggle('nav-open',open);menuToggle.setAttribute('aria-expanded',String(open));
    backdrop.hidden=!open;shell.inert=open;
    if(open)requestAnimationFrame(()=>{if(document.body.classList.contains('nav-open'))sideNav.querySelector('[data-menu-close]').focus();});else if(returnFocus)menuToggle.focus();
  }
  menuToggle.addEventListener('click',()=>setMenu(!document.body.classList.contains('nav-open')));
  document.querySelectorAll('[data-menu-close]').forEach(b=>b.addEventListener('click',()=>setMenu(false)));
  document.addEventListener('keydown',e=>{
    if(!document.body.classList.contains('nav-open'))return;
    if(e.key==='Escape'){e.preventDefault();setMenu(false);return;}
    if(e.key==='Tab'){
      const items=[...sideNav.querySelectorAll('a[href],button')].filter(x=>x.getClientRects().length),first=items[0],last=items[items.length-1];
      if(!sideNav.contains(document.activeElement)){e.preventDefault();first.focus();}
      else if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
    }
  });
  mobile.addEventListener('change',()=>setMenu(false,false));
}
function drawChart(canvas){
  const input=document.getElementById(canvas.dataset.chart);if(!input)return;
  const data=JSON.parse(input.textContent),ctx=canvas.getContext('2d');
  const w=canvas.clientWidth,h=230,dpr=window.devicePixelRatio||1;
  canvas.width=w*dpr;canvas.height=h*dpr;ctx.scale(dpr,dpr);
  const pts=data.values.map(v=>v===null?null:Number(v)),valid=pts.filter(v=>v!==null&&Number.isFinite(v));
  if(!valid.length){ctx.fillStyle='#748078';ctx.fillText('Chưa có dữ liệu',20,40);return;}
  const lo=Math.min(0,...valid),hi=Math.max(1,...valid),left=72,right=w-44,top=20,bottom=184;
  ctx.font='12px "Be Vietnam Pro", -apple-system, "Segoe UI", sans-serif';ctx.lineWidth=1;
  for(let i=0;i<5;i++){const v=lo+(hi-lo)*i/4,y=bottom-(bottom-top)*i/4;ctx.strokeStyle='#e8ebef';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.fillStyle='#6b7280';ctx.fillText(new Intl.NumberFormat('vi-VN',{notation:'compact',maximumFractionDigits:1}).format(v),3,y+4);}
  const x=i=>left+(right-left)*i/Math.max(1,pts.length-1),y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
  ctx.strokeStyle='#0f6b5b';ctx.lineWidth=2.2;ctx.beginPath();let started=false;
  pts.forEach((v,i)=>{if(v===null||!Number.isFinite(v)){started=false;return;}if(started)ctx.lineTo(x(i),y(v));else ctx.moveTo(x(i),y(v));started=true;});ctx.stroke();
  pts.forEach((v,i)=>{if(v===null)return;ctx.fillStyle='#0f6b5b';ctx.beginPath();ctx.arc(x(i),y(v),3,0,Math.PI*2);ctx.fill();});
  const maxLabels=Math.max(2,Math.floor((right-left)/85)+1);
  const step=Math.max(1,Math.ceil((data.labels.length-1)/(maxLabels-1)));
  ctx.fillStyle='#5c6370';ctx.textAlign='center';
  data.labels.forEach((label,i)=>{
    const last=data.labels.length-1;
    if(i===last||(i%step===0&&(last-i>=step)))ctx.fillText(label,x(i),210);
  });
}
document.querySelectorAll('canvas[data-chart]').forEach(c=>{drawChart(c);new ResizeObserver(()=>drawChart(c)).observe(c);});
