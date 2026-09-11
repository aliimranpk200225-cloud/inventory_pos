(function () {
  const config = window.POS_CONFIG || {};
  const cart = [];
  let saleId = null;

  const searchInput = document.getElementById('product-search');
  const resultsEl = document.getElementById('product-results');
  const cartBody = document.getElementById('cart-body');
  const errorEl = document.getElementById('pos-error');
  const draftEl = document.getElementById('pos-draft');
  let searchTimer = null;

  function moneyNumber(value) {
    const n = Number(value);
    return (Number.isFinite(n) ? n : 0).toFixed(2);
  }

  function money(value) {
    const parts = moneyNumber(value).split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return parts.join('.');
  }

  function formatQty(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '0';
    const rounded = Math.round(n * 100) / 100;
    if (Object.is(rounded, -0)) return '0';
    if (Number.isInteger(rounded)) return String(rounded);
    return String(rounded);
  }

  function stockInSelectedUnit(item) {
    if (item.stock_in_unit != null && item.stock_in_unit !== '') {
      return formatQty(item.stock_in_unit);
    }
    const onHand = Number(item.stock_on_hand) || 0;
    const conversion = Number(item.conversion_to_base) || 1;
    return formatQty(conversion ? onHand / conversion : onHand);
  }

  function stockLabel(item) {
    return stockInSelectedUnit(item) + ' ' + item.unit + ' on hand';
  }

  function lineAmounts(item) {
    const qty = Number(item.quantity) || 0;
    const price = Number(item.unit_price) || 0;
    const gross = qty * price;
    let discount = Number(item.discount_value) || 0;
    if (item.discount_type === 'percent') {
      discount = gross * discount / 100;
    }
    if (discount > gross) discount = gross;
    const total = Math.max(0, gross - discount);
    return { gross, discount, total };
  }

  function invoiceAmounts() {
    const subtotal = cart.reduce((sum, item) => sum + lineAmounts(item).total, 0);
    const type = document.getElementById('invoice-discount-type').value;
    const value = Number(document.getElementById('invoice-discount-value').value) || 0;
    let discount = type === 'percent' ? subtotal * value / 100 : value;
    if (discount > subtotal) discount = subtotal;
    const tax = Number(document.getElementById('invoice-tax').value) || 0;
    const total = Math.max(0, subtotal - discount + tax);
    const paidField = document.getElementById('paid-amount').value;
    const paid = paidField === '' ? total : (Number(paidField) || 0);
    const due = Math.max(0, total - paid);
    const change = Math.max(0, paid - total);
    return { subtotal, discount, tax, total, paid, due, change };
  }

  function updateTotals() {
    const totals = invoiceAmounts();
    document.getElementById('sum-subtotal').textContent = money(totals.subtotal);
    document.getElementById('sum-discount').textContent = money(totals.discount);
    document.getElementById('sum-tax').textContent = money(totals.tax);
    document.getElementById('sum-total').textContent = money(totals.total);
    document.getElementById('sum-paid').textContent = money(totals.paid);
    document.getElementById('sum-due').textContent = money(totals.due);
    document.getElementById('sum-change').textContent = money(totals.change);
    const paid = document.getElementById('paid-amount');
    if (!paid.value) {
      paid.placeholder = money(totals.total);
    }
    const dueRow = document.getElementById('row-due');
    const changeRow = document.getElementById('row-change');
    dueRow.classList.toggle('is-due', totals.due > 0);
    changeRow.classList.toggle('is-change', totals.change > 0);
  }

  const PERCENT_PRESETS = ['0', '5', '10', '15', '20'];
  const FIXED_PRESETS = ['50', '100', '200', '500'];
  const ITEM_FIXED_PRESETS = ['10', '20', '50', '100'];
  let pendingCustomFocus = null;

  function discountAmountKey(value) {
    return String(Number(value) || 0);
  }

  function isPresetAmount(value, presets) {
    return presets.indexOf(discountAmountKey(value)) !== -1;
  }

  function itemDiscIsCustom(item) {
    if (item.discount_custom) return true;
    const type = item.discount_type === 'percent' ? 'percent' : 'fixed';
    const presets = type === 'percent' ? PERCENT_PRESETS : ITEM_FIXED_PRESETS;
    if (type === 'fixed' && Number(item.discount_value) === 0) return false;
    return !isPresetAmount(item.discount_value, presets);
  }

  function radioChecked(condition) {
    return condition ? ' checked' : '';
  }

  function itemDiscHtml(item, index) {
    const type = item.discount_type === 'percent' ? 'percent' : 'fixed';
    const amount = discountAmountKey(item.discount_value);
    const isCustom = itemDiscIsCustom(item);
    const prefix = type === 'percent' ? '%' : 'Rs.';
    const percentButtons = PERCENT_PRESETS.map(function (value) {
      return (
        '<input type="radio" class="btn-check item-pct-preset" name="item-pct-' + index + '" id="item-pct-' + index + '-' + value + '" value="' + value + '"' +
          radioChecked(type === 'percent' && !isCustom && amount === value) + '>' +
        '<label class="btn btn-outline-primary" for="item-pct-' + index + '-' + value + '">' + value + '%</label>'
      );
    }).join('') +
      '<input type="radio" class="btn-check item-pct-preset" name="item-pct-' + index + '" id="item-pct-' + index + '-custom" value="custom"' +
        radioChecked(type === 'percent' && isCustom) + '>' +
      '<label class="btn btn-outline-primary" for="item-pct-' + index + '-custom">Custom</label>';
    const fixedButtons = ITEM_FIXED_PRESETS.map(function (value) {
      return (
        '<input type="radio" class="btn-check item-fix-preset" name="item-fix-' + index + '" id="item-fix-' + index + '-' + value + '" value="' + value + '"' +
          radioChecked(type === 'fixed' && !isCustom && amount === value) + '>' +
        '<label class="btn btn-outline-primary" for="item-fix-' + index + '-' + value + '">Rs.' + value + '</label>'
      );
    }).join('') +
      '<input type="radio" class="btn-check item-fix-preset" name="item-fix-' + index + '" id="item-fix-' + index + '-custom" value="custom"' +
        radioChecked(type === 'fixed' && isCustom) + '>' +
      '<label class="btn btn-outline-primary" for="item-fix-' + index + '-custom">Custom</label>';

    return (
      '<div class="item-disc">' +
        '<div class="btn-group btn-group-sm item-disc-type-group" role="group" aria-label="Discount type">' +
          '<input type="radio" class="btn-check item-disc-type" name="item-disc-type-' + index + '" id="item-disc-type-pct-' + index + '" value="percent"' + radioChecked(type === 'percent') + '>' +
          '<label class="btn btn-outline-primary" for="item-disc-type-pct-' + index + '">%</label>' +
          '<input type="radio" class="btn-check item-disc-type" name="item-disc-type-' + index + '" id="item-disc-type-rs-' + index + '" value="fixed"' + radioChecked(type === 'fixed') + '>' +
          '<label class="btn btn-outline-primary" for="item-disc-type-rs-' + index + '">Rs.</label>' +
        '</div>' +
        '<div class="item-pct-presets' + (type === 'percent' ? '' : ' d-none') + '">' +
          '<div class="btn-group btn-group-sm flex-wrap" role="group" aria-label="Percentage discount">' + percentButtons + '</div>' +
        '</div>' +
        '<div class="item-fix-presets' + (type === 'fixed' ? '' : ' d-none') + '">' +
          '<div class="btn-group btn-group-sm flex-wrap" role="group" aria-label="Fixed discount">' + fixedButtons + '</div>' +
        '</div>' +
        '<div class="input-group input-group-sm item-custom-disc mt-1' + (isCustom ? '' : ' d-none') + '">' +
          '<span class="input-group-text">' + prefix + '</span>' +
          '<input class="form-control item-custom-disc-input" type="number" min="0" step="0.01" value="' + moneyNumber(item.discount_value) + '" placeholder="Amount">' +
        '</div>' +
      '</div>'
    );
  }

  function discountType() {
    return document.getElementById('invoice-discount-type').value;
  }

  function setDiscount(type, value, fromCustom) {
    document.getElementById('invoice-discount-type').value = type;
    document.getElementById('invoice-discount-value').value = value;
    document.getElementById('disc-type-percent').checked = type === 'percent';
    document.getElementById('disc-type-fixed').checked = type === 'fixed';
    document.getElementById('percent-presets').classList.toggle('d-none', type !== 'percent');
    document.getElementById('fixed-presets').classList.toggle('d-none', type !== 'fixed');
    document.getElementById('custom-discount-prefix').textContent = type === 'percent' ? '%' : 'Rs.';

    const presets = type === 'percent' ? PERCENT_PRESETS : FIXED_PRESETS;
    const amount = String(Number(value) || 0);
    const isPreset = !fromCustom && isPresetAmount(value, presets);
    const customWrap = document.getElementById('custom-discount');
    const customInput = document.getElementById('custom-discount-input');
    const groupName = type === 'percent' ? 'percent-preset' : 'fixed-preset';
    const hideCustomZeroFixed = type === 'fixed' && !isPreset && Number(value) === 0 && !fromCustom;

    document.querySelectorAll('input[name="' + groupName + '"]').forEach(function (input) {
      if (hideCustomZeroFixed) input.checked = false;
      else if (isPreset) input.checked = input.value === amount;
      else input.checked = input.value === 'custom';
    });

    if (hideCustomZeroFixed) {
      customWrap.classList.add('d-none');
    } else {
      customWrap.classList.toggle('d-none', isPreset);
      if (!isPreset && document.activeElement !== customInput) {
        customInput.value = value;
      }
    }
    updateTotals();
  }

  function syncDiscountUI() {
    const type = discountType();
    const value = document.getElementById('invoice-discount-value').value || '0';
    const presets = type === 'percent' ? PERCENT_PRESETS : FIXED_PRESETS;
    setDiscount(type, value, !isPresetAmount(value, presets) && !(type === 'fixed' && Number(value) === 0));
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  function availableBase(item) {
    return Number(item.stock_on_hand) || 0;
  }

  function neededBase(item, quantity) {
    const qty = Number(quantity);
    const conversion = Number(item.conversion_to_base) || 1;
    return (Number.isFinite(qty) ? qty : 0) * conversion;
  }

  function stockBadge(status) {
    if (status === 'out') return '<span class="stock-badge out">Out of stock</span>';
    if (status === 'low') return '<span class="stock-badge low">Low stock</span>';
    return '';
  }

  function renderCart() {
    if (!cart.length) {
      cartBody.innerHTML = '<tr class="empty-cart"><td colspan="6">Select products to add them to the invoice.</td></tr>';
    } else {
      cartBody.innerHTML = cart.map(function (item, index) {
        const amounts = lineAmounts(item);
        const remaining = availableBase(item) - neededBase(item, item.quantity);
        const warn = remaining < 0
          ? '<div class="cart-stock-warn">Exceeds on-hand stock</div>'
          : (item.stock_status === 'low' ? '<div class="cart-stock-warn">Low stock (' + stockLabel(item) + ')</div>' : '');
        return (
          '<tr data-index="' + index + '">' +
            '<td><strong>' + item.name + '</strong><div class="meta">' + item.sku + ' · ' + item.unit + '</div>' +
              '<div class="meta">' + stockLabel(item) + '</div>' + warn + '</td>' +
            '<td class="qty-cell"><input class="qty" type="number" min="0.0001" step="1" value="' + formatQty(item.quantity) + '"> <span class="qty-unit">' + item.unit + '</span></td>' +
            '<td><input class="price" type="number" min="0" step="0.01" value="' + Number(item.unit_price) + '"></td>' +
            '<td class="item-disc-cell">' + itemDiscHtml(item, index) + '</td>' +
            '<td class="line-total">' + money(amounts.total) + '</td>' +
            '<td><button type="button" class="remove" aria-label="Remove">×</button></td>' +
          '</tr>'
        );
      }).join('');
    }
    updateTotals();
    if (pendingCustomFocus != null) {
      const row = cartBody.querySelector('tr[data-index="' + pendingCustomFocus + '"]');
      const input = row && row.querySelector('.item-custom-disc-input');
      pendingCustomFocus = null;
      if (input) input.focus();
    }
  }

  function addProduct(product) {
    const nextQty = (function () {
      const existing = cart.find(function (item) { return item.product_unit_id === product.id; });
      return existing ? Number(existing.quantity) + 1 : 1;
    })();
    const needed = neededBase(product, nextQty);
    if (!config.allowNegativeStock && needed > availableBase(product)) {
      if (availableBase(product) <= 0) {
        showError(product.name + ' is out of stock.');
      } else {
        showError('Not enough stock for ' + product.name + ' (' + stockLabel(product) + ').');
      }
      return;
    }
    showError('');
    const existing = cart.find(function (item) { return item.product_unit_id === product.id; });
    if (existing) {
      existing.quantity = nextQty;
    } else {
      cart.push({
        product_unit_id: product.id,
        sku: product.sku,
        name: product.name,
        unit: product.unit,
        base_unit: product.base_unit,
        quantity: 1,
        unit_price: product.retail_price,
        discount_type: 'percent',
        discount_value: 0,
        discount_custom: false,
        conversion_to_base: product.conversion_to_base,
        stock_on_hand: product.stock_on_hand,
        stock_in_unit: product.stock_in_unit,
        stock_status: product.stock_status,
      });
    }
    renderCart();
  }

  function productCardMarkup(product) {
    const statusClass = product.stock_status === 'out' ? ' out-of-stock' : (product.stock_status === 'low' ? ' low-stock' : '');
    const imageUrl = product.image_url ? String(product.image_url) : '';
    const imageClass = imageUrl ? ' has-image' : '';
    const imageStyle = imageUrl
      ? ' style="--product-image:url(\'' + imageUrl.replace(/\\/g, '/').replace(/'/g, '%27') + '\')"'
      : '';
    return (
      '<button type="button" class="product-card' + statusClass + imageClass + '" data-id="' + product.id + '"' + imageStyle + '>' +
        '<strong>' + product.name + '</strong>' +
        '<div class="meta">' + product.sku + ' · ' + product.unit + '</div>' +
        '<div class="price">Rs. ' + money(product.retail_price) + '</div>' +
        '<div class="stock-line">' +
          '<span>' + stockLabel(product) + '</span>' +
          stockBadge(product.stock_status) +
        '</div>' +
      '</button>'
    );
  }

  function renderProducts(products) {
    if (!products.length) {
      resultsEl.innerHTML = '<p class="lede">No matching products.</p>';
      return;
    }
    resultsEl.innerHTML = products.map(productCardMarkup).join('');
    resultsEl.querySelectorAll('.product-card').forEach(function (button) {
      button.addEventListener('click', function () {
        const product = products.find(function (row) { return String(row.id) === button.dataset.id; });
        if (product) addProduct(product);
      });
    });
  }

  function searchProducts(query) {
    const url = config.productsUrl + '?q=' + encodeURIComponent(query || '');
    fetch(url, { credentials: 'same-origin' })
      .then(function (response) { return response.json(); })
      .then(function (data) { renderProducts(data.results || []); })
      .catch(function () { resultsEl.innerHTML = '<p class="pos-error">Could not load products.</p>'; });
  }

  searchInput.addEventListener('input', function () {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () { searchProducts(searchInput.value); }, 200);
  });

  function applyItemDiscount(index, type, value, fromCustom) {
    const item = cart[index];
    if (!item) return;
    item.discount_type = type;
    if (value !== undefined) item.discount_value = value;
    item.discount_custom = !!fromCustom;
    if (fromCustom) pendingCustomFocus = index;
    renderCart();
  }

  cartBody.addEventListener('input', function (event) {
    const row = event.target.closest('tr[data-index]');
    if (!row) return;
    const item = cart[Number(row.dataset.index)];
    if (!item) return;
    if (event.target.classList.contains('btn-check')) return;
    if (event.target.classList.contains('qty')) item.quantity = event.target.value;
    if (event.target.classList.contains('price')) item.unit_price = event.target.value;
    if (event.target.classList.contains('item-custom-disc-input')) {
      item.discount_value = event.target.value;
      item.discount_custom = true;
    }
    const amounts = lineAmounts(item);
    const totalCell = row.querySelector('.line-total');
    if (totalCell) totalCell.textContent = money(amounts.total);
    const metaCell = row.querySelector('td');
    if (metaCell && event.target.classList.contains('qty')) {
      let warn = metaCell.querySelector('.cart-stock-warn');
      const remaining = availableBase(item) - neededBase(item, item.quantity);
      const text = remaining < 0
        ? 'Exceeds on-hand stock'
        : (item.stock_status === 'low' ? 'Low stock (' + stockLabel(item) + ')' : '');
      if (text) {
        if (!warn) {
          warn = document.createElement('div');
          warn.className = 'cart-stock-warn';
          metaCell.appendChild(warn);
        }
        warn.textContent = text;
      } else if (warn) {
        warn.remove();
      }
    }
    updateTotals();
  });

  cartBody.addEventListener('change', function (event) {
    const row = event.target.closest('tr[data-index]');
    if (!row) return;
    const index = Number(row.dataset.index);
    const item = cart[index];
    if (!item) return;
    const target = event.target;
    if (target.classList.contains('item-disc-type')) {
      applyItemDiscount(index, target.value, 0);
      return;
    }
    if (target.classList.contains('item-pct-preset')) {
      if (target.value === 'custom') applyItemDiscount(index, 'percent', item.discount_value, true);
      else applyItemDiscount(index, 'percent', target.value);
      return;
    }
    if (target.classList.contains('item-fix-preset')) {
      if (target.value === 'custom') applyItemDiscount(index, 'fixed', item.discount_value, true);
      else applyItemDiscount(index, 'fixed', target.value);
    }
  });

  cartBody.addEventListener('click', function (event) {
    if (!event.target.classList.contains('remove')) return;
    const row = event.target.closest('tr[data-index]');
    cart.splice(Number(row.dataset.index), 1);
    renderCart();
  });

  ['invoice-tax', 'paid-amount'].forEach(function (id) {
    document.getElementById(id).addEventListener('input', updateTotals);
    document.getElementById(id).addEventListener('change', updateTotals);
  });

  document.querySelectorAll('input[name="discount-type-ui"]').forEach(function (input) {
    input.addEventListener('change', function () {
      setDiscount(this.value, '0');
    });
  });

  document.querySelectorAll('input[name="percent-preset"]').forEach(function (input) {
    input.addEventListener('change', function () {
      if (this.value === 'custom') {
        setDiscount('percent', document.getElementById('custom-discount-input').value || '0', true);
        document.getElementById('custom-discount-input').focus();
      } else {
        setDiscount('percent', this.value);
      }
    });
  });

  document.querySelectorAll('input[name="fixed-preset"]').forEach(function (input) {
    input.addEventListener('change', function () {
      if (this.value === 'custom') {
        setDiscount('fixed', document.getElementById('custom-discount-input').value || '0', true);
        document.getElementById('custom-discount-input').focus();
      } else {
        setDiscount('fixed', this.value);
      }
    });
  });

  document.getElementById('custom-discount-input').addEventListener('input', function () {
    setDiscount(discountType(), this.value || '0', true);
  });

  document.getElementById('customer-phone').addEventListener('blur', function () {
    const phone = this.value.trim();
    if (!phone) return;
    fetch(config.customersUrl + '?phone=' + encodeURIComponent(phone), { credentials: 'same-origin' })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (!data.customer) return;
        document.getElementById('customer-name').value = data.customer.name || '';
      });
  });

  function selectedPaymentMethod() {
    const checked = document.querySelector('input[name="payment_method"]:checked');
    return checked ? checked.value : 'cash';
  }

  function setPaymentMethod(method) {
    const radio = document.getElementById('pay-' + (method || 'cash'));
    if (radio) radio.checked = true;
    else document.getElementById('pay-cash').checked = true;
  }

  function buildPayload(forDraft) {
    const totals = invoiceAmounts();
    const paidField = document.getElementById('paid-amount').value;
    const payload = {
      customer: {
        name: document.getElementById('customer-name').value,
        phone: document.getElementById('customer-phone').value,
      },
      items: cart.map(function (item) {
        return {
          product_unit_id: item.product_unit_id,
          quantity: item.quantity,
          unit_price: item.unit_price,
          discount_type: item.discount_type,
          discount_value: item.discount_value,
        };
      }),
      discount_type: document.getElementById('invoice-discount-type').value,
      discount_value: document.getElementById('invoice-discount-value').value,
      tax: document.getElementById('invoice-tax').value,
      paid_amount: forDraft ? (paidField || '0') : (paidField === '' ? moneyNumber(totals.total) : paidField),
      payment_method: selectedPaymentMethod(),
    };
    if (saleId) payload.sale_id = saleId;
    return payload;
  }

  function postSale(url, payload, onOk) {
    fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': config.csrfToken,
      },
      body: JSON.stringify(payload),
    })
      .then(function (response) { return response.json().then(function (data) { return { ok: response.ok, data: data }; }); })
      .then(function (result) {
        if (!result.ok) {
          showError(result.data.error || 'Could not save the order.');
          return;
        }
        onOk(result.data);
      })
      .catch(function () {
        showError('Could not save the order.');
      });
  }

  function loadDraft(draft) {
    if (!draft) return;
    saleId = draft.sale_id || null;
    document.getElementById('customer-phone').value = draft.customer_phone || '';
    document.getElementById('customer-name').value = draft.customer_name || '';
    document.getElementById('invoice-discount-type').value = draft.discount_type || 'fixed';
    document.getElementById('invoice-discount-value').value = draft.discount_value || '0';
    document.getElementById('invoice-tax').value = draft.tax || '0';
    setPaymentMethod(draft.payment_method || 'cash');
    document.getElementById('paid-amount').value = Number(draft.paid_amount) ? draft.paid_amount : '';
    (draft.items || []).forEach(function (item) {
      cart.push({
        product_unit_id: item.product_unit_id,
        sku: item.sku,
        name: item.name,
        unit: item.unit,
        base_unit: item.base_unit,
        quantity: item.quantity,
        unit_price: item.unit_price,
        discount_type: item.discount_type || 'percent',
        discount_value: item.discount_value || 0,
        discount_custom: false,
        conversion_to_base: item.conversion_to_base,
        stock_on_hand: item.stock_on_hand,
        stock_in_unit: item.stock_in_unit,
        stock_status: item.stock_status,
      });
    });
    syncDiscountUI();
  }

  document.getElementById('checkout-btn').addEventListener('click', function () {
    showError('');
    if (!config.allowNegativeStock) {
      const oversold = cart.find(function (item) {
        return neededBase(item, item.quantity) > availableBase(item);
      });
      if (oversold) {
        showError('Not enough stock for ' + oversold.name + ' (' + stockLabel(oversold) + ').');
        return;
      }
    }
    postSale(config.checkoutUrl, buildPayload(false), function (data) {
      window.location.href = data.invoice_url;
    });
  });

  document.getElementById('draft-btn').addEventListener('click', function () {
    showError('');
    postSale(config.draftUrl, buildPayload(true), function (data) {
      window.location.href = data.day_url || config.dayUrl;
    });
  });

  if (draftEl) {
    try {
      loadDraft(JSON.parse(draftEl.textContent));
    } catch (err) {
      showError('Could not load the draft order.');
    }
  }

  searchProducts('');
  syncDiscountUI();
  renderCart();
})();
