document.querySelectorAll('form[data-sale-payment]').forEach(form=>{
  const radios=[...form.querySelectorAll('input[name="method"]')];
  const cash=form.querySelector('[data-payment-cash]');
  const transfer=form.querySelector('[data-payment-transfer]');
  function update(){
    const method=radios.find(input=>input.checked)?.value;
    for(const [section,enabled] of [[cash,method==='CASH'],[transfer,method==='TRANSFER']]){
      if(!section)continue;section.hidden=!enabled;
      section.querySelectorAll('input').forEach(input=>{input.disabled=!enabled;if(input.name==='transfer_ack')input.required=enabled;});
    }
  }
  radios.forEach(input=>input.addEventListener('change',update));update();
});
