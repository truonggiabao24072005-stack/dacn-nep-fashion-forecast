const menuButton=document.querySelector('[data-menu-toggle]');
const mainNav=document.querySelector('#main-nav');
function setMenu(expanded){menuButton?.setAttribute('aria-expanded',String(expanded));mainNav?.classList.toggle('is-open',expanded);}
menuButton?.addEventListener('click',()=>setMenu(menuButton.getAttribute('aria-expanded')!=='true'));
document.addEventListener('click',event=>{if(menuButton?.getAttribute('aria-expanded')==='true'&&!menuButton.contains(event.target)&&!mainNav?.contains(event.target))setMenu(false);});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&menuButton?.getAttribute('aria-expanded')==='true'){setMenu(false);menuButton.focus();}});
window.matchMedia('(min-width:1101px)').addEventListener('change',()=>setMenu(false));
const filterToggle = document.querySelector('[data-filter-toggle]');
if (filterToggle) {
  const filters = document.getElementById(filterToggle.getAttribute('aria-controls'));
  const mobile = window.matchMedia('(max-width: 820px)');
  const searchRequested = new URLSearchParams(location.search).get('focus') === 'search';
  function setFilters(open) {
    filters.hidden = !open;
    filterToggle.setAttribute('aria-expanded', String(open));
  }
  function updateFilterLayout(showSearch = false) {
    filterToggle.hidden = !mobile.matches;
    setFilters(!mobile.matches || showSearch);
  }
  filterToggle.addEventListener('click', () => setFilters(filters.hidden));
  mobile.addEventListener('change', () => updateFilterLayout(filters.contains(document.activeElement)));
  updateFilterLayout(searchRequested);
  if (searchRequested) document.getElementById('search-input')?.focus();
}
const productForm=document.querySelector('[data-product-form]');
if(productForm){
  const variants=JSON.parse(document.querySelector('#product-variants').textContent);
  const price=document.querySelector('[data-variant-price]'),stock=document.querySelector('[data-variant-stock]'),sku=document.querySelector('[data-variant-sku]');
  const input=productForm.querySelector('[data-quantity]'),button=productForm.querySelector('[data-add-button]'),variantInput=productForm.querySelector('[data-variant-id]');
  const money=n=>new Intl.NumberFormat('vi-VN').format(BigInt(n))+' đ';
  function update(){
    const color=Number(productForm.querySelector('[name=color_choice]:checked')?.value),size=Number(productForm.querySelector('[name=size_choice]:checked')?.value);
    const v=variants.find(v=>v.color===color&&v.size===size);
    const label=productForm.querySelector('[name=color_choice]:checked')?.closest('label')?.querySelector('span:last-child')?.textContent;
    document.querySelector('[data-color-name]').textContent=label||'';
    variantInput.value=v?.id||'';sku.textContent=v?.sku||'Không có kích thước và màu đã chọn.';
    price.textContent=v?money(v.price):'Chưa có giá';
    const maximum=Math.min(99,v?.stock||0);input.max=Math.max(1,maximum);input.value=Math.min(Math.max(1,Number(input.value)||1),Math.max(1,maximum));
    stock.textContent=v&&maximum>0?'Còn '+v.stock+' sản phẩm':v?'Lựa chọn này tạm hết hàng':'Chưa có sản phẩm cho cỡ và màu này.';
    stock.classList.toggle('unavailable',maximum===0);button.disabled=maximum===0;
    productForm.querySelectorAll('[data-qty]').forEach(b=>b.disabled=maximum===0||(Number(b.dataset.qty)<0&&Number(input.value)<=1)||(Number(b.dataset.qty)>0&&Number(input.value)>=maximum));
  }
  const variantSelect = productForm.querySelector('[data-variant-select]');
  if (variantSelect) {
    variantSelect.hidden = true;
    variantSelect.querySelector('select').disabled = true;
    variantInput.disabled = false;
    productForm.querySelector('[data-variant-controls]').hidden = false;
  }
  productForm.querySelectorAll('[name=color_choice],[name=size_choice]').forEach(e=>e.addEventListener('change',update));
  productForm.querySelectorAll('[data-qty]').forEach(b=>{
    b.hidden = false;
    b.addEventListener('click',()=>{input.value=Number(input.value)+Number(b.dataset.qty);update();});
  });
  input.addEventListener('change',update);update();
}
const gallery=document.querySelector('[data-product-gallery]');
if(gallery){
  const dialog=gallery.querySelector('#product-image-dialog');
  const thumbs=[...gallery.querySelectorAll('[data-gallery-thumb]')];
  const main=gallery.querySelector('[data-gallery-main]'),zoom=gallery.querySelector('[data-gallery-zoom]');
  let current=0;
  function showImage(index){
    if(!thumbs.length)return;
    current=(index+thumbs.length)%thumbs.length;
    const thumb=thumbs[current];
    for(const image of [main,zoom]){if(image){image.src=thumb.dataset.gallerySrc;image.alt=thumb.dataset.galleryAlt;}}
    thumbs.forEach((button,i)=>button.setAttribute('aria-current',String(i===current)));
    gallery.querySelectorAll('[data-gallery-count]').forEach(e=>e.textContent=(current+1)+' / '+thumbs.length);
    const label=gallery.querySelector('[data-gallery-label]:not([data-gallery-thumb])');if(label)label.textContent=thumb.dataset.galleryLabel;
    const source=gallery.querySelector('[data-gallery-source-link]');
    if(source){source.href=thumb.dataset.gallerySource;source.textContent=thumb.dataset.galleryCredit;}
    const strip=thumb.parentElement;
    if(strip.scrollWidth>strip.clientWidth)strip.scrollTo({left:Math.max(0,thumb.offsetLeft-(strip.clientWidth-thumb.clientWidth)/2),behavior:'auto'});
  }
  thumbs.forEach((thumb,index)=>thumb.addEventListener('click',()=>showImage(index)));
  gallery.querySelectorAll('[data-gallery-prev]').forEach(button=>button.addEventListener('click',()=>showImage(current-1)));
  gallery.querySelectorAll('[data-gallery-next]').forEach(button=>button.addEventListener('click',()=>showImage(current+1)));
  gallery.addEventListener('keydown',event=>{
    if(event.altKey||event.ctrlKey||event.metaKey||!thumbs.length||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    showImage(event.key==='Home'?0:event.key==='End'?thumbs.length-1:current+(event.key==='ArrowLeft'?-1:1));
    if(!dialog?.open)thumbs[current].focus({preventScroll:true});
  });
  gallery.querySelector('[data-open-image]')?.addEventListener('click',()=>dialog?.showModal());
  gallery.querySelector('[data-close-dialog]')?.addEventListener('click',()=>dialog?.close());
  dialog?.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
}
const pickupLocation = document.querySelector('[data-pickup-location]');
const deliveryAddress = document.getElementById('id_delivery_address');
if (pickupLocation && deliveryAddress) {
  const updatePickupLocation = () => {
    pickupLocation.hidden = Boolean(deliveryAddress.value.trim());
  };
  deliveryAddress.addEventListener('input', updatePickupLocation);
  updatePickupLocation();
}
document.querySelector('[data-checkout-form]')?.addEventListener('submit',e=>{if(e.target.checkValidity()){const b=e.target.querySelector('button[type=submit],button:not([type])');if(b){b.disabled=true;b.setAttribute('aria-busy','true');b.textContent='Đang gửi đơn…';}}});

// Password visibility stays local to the form and does not store credentials.
document.querySelectorAll('[data-password-toggle]').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.getAttribute('aria-controls'));
    if (!input) return;
    const reveal = input.type === 'password';
    input.type = reveal ? 'text' : 'password';
    button.textContent = reveal ? 'Ẩn' : 'Hiện';
    button.setAttribute('aria-pressed', String(reveal));
    button.setAttribute('aria-label', (reveal ? 'Ẩn ' : 'Hiện ') + document.querySelector('label[for="' + input.id + '"]').textContent.toLowerCase());
  });
});
