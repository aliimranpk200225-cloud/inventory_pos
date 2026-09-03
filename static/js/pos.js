(function () {
  const config = window.POS_CONFIG || {};
  const cart = [];

  const searchInput = document.getElementById('product-search');
  const resultsEl = document.getElementById('product-results');
  const cartBody = document.getElementById('cart-body');
  const errorEl = document.getElementById('pos-error');
  let searchTimer = null;

  function money(value) {
    const n = Number(value);
    return (Number.isFinite(n) ? n : 0).toFixed(2);
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
    return { subtotal, discount, tax, total };
  }

  function updateTotals() {
    const totals = invoiceAmounts();
    document.getElementById('sum-subtotal').textContent = money(totals.subtotal);
    document.getElementById('sum-discount').textContent = money(totals.discount);
    document.getElementById('sum-tax').textContent = money(totals.tax);
    document.getElementById('sum-total').textContent = money(totals.total);
    const paid = document.getElementById('paid-amount');
    if (!paid.value) {
      paid.placeholder = money(totals.total);
    }
  }

  function renderCart() {
    if (!cart.length) {
      cartBody.innerHTML = '<tr class="empty-cart"><td colspan="6">Select products to add them to the invoice.</td></tr>';
    } else {
      cartBody.innerHTML = cart.map(function (item, index) {
        const amounts = lineAmounts(item);
        return (
          '<tr data-index="' + index + '">' +
            '<td><strong>' + item.name + '</strong><div class="meta">' + item.sku + ' · ' + item.unit + '</div></td>' +
            '<td><input class="qty" type="number" min="0.0001" step="1" value="' + item.quantity + '"></td>' +
            '<td><input class="price" type="number" min="0" step="0.01" value="' + item.unit_price + '"></td>' +
            '<td>' +
              '<select class="disc-type">' +
                '<option value="fixed"' + (item.discount_type === 'fixed' ? ' selected' : '') + '>Rs.</option>' +
                '<option value="percent"' + (item.discount_type === 'percent' ? ' selected' : '') + '>%</option>' +
              '</select>' +
              '<input class="disc-value" type="number" min="0" step="0.01" value="' + item.discount_value + '">' +
            '</td>' +
            '<td class="line-total">' + money(amounts.total) + '</td>' +
            '<td><button type="button" class="remove" aria-label="Remove">×</button></td>' +
          '</tr>'
        );
      }).join('');
    }
    updateTotals();
  }

  function addProduct(product) {
    const existing = cart.find(function (item) { return item.product_unit_id === product.id; });
    if (existing) {
      existing.quantity = Number(existing.quantity) + 1;
    } else {
      cart.push({
        product_unit_id: product.id,
        sku: product.sku,
        name: product.name,
        unit: product.unit,
        quantity: 1,
        unit_price: product.retail_price,
        discount_type: 'fixed',
        discount_value: 0,
      });
    }
    renderCart();
  }

  function renderProducts(products) {
    if (!products.length) {
      resultsEl.innerHTML = '<p class="lede">No matching products.</p>';
      return;
    }
    resultsEl.innerHTML = products.map(function (product) {
      return (
        '<button type="button" class="product-card" data-id="' + product.id + '">' +
          '<strong>' + product.name + '</strong>' +
          '<div class="meta">' + product.sku + ' · ' + product.unit + '</div>' +
          '<div class="price">Rs. ' + money(product.retail_price) + '</div>' +
        '</button>'
      );
    }).join('');
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

  cartBody.addEventListener('input', function (event) {
    const row = event.target.closest('tr[data-index]');
    if (!row) return;
    const item = cart[Number(row.dataset.index)];
    if (event.target.classList.contains('qty')) item.quantity = event.target.value;
    if (event.target.classList.contains('price')) item.unit_price = event.target.value;
    if (event.target.classList.contains('disc-type')) item.discount_type = event.target.value;
    if (event.target.classList.contains('disc-value')) item.discount_value = event.target.value;
    const amounts = lineAmounts(item);
    const totalCell = row.querySelector('.line-total');
    if (totalCell) totalCell.textContent = money(amounts.total);
    updateTotals();
  });

  cartBody.addEventListener('click', function (event) {
    if (!event.target.classList.contains('remove')) return;
    const row = event.target.closest('tr[data-index]');
    cart.splice(Number(row.dataset.index), 1);
    renderCart();
  });

  ['invoice-discount-type', 'invoice-discount-value', 'invoice-tax'].forEach(function (id) {
    document.getElementById(id).addEventListener('input', renderCart);
    document.getElementById(id).addEventListener('change', renderCart);
  });

  document.getElementById('customer-phone').addEventListener('blur', function () {
    const phone = this.value.trim();
    if (!phone) return;
    fetch(config.customersUrl + '?phone=' + encodeURIComponent(phone), { credentials: 'same-origin' })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        if (!data.customer) return;
        document.getElementById('customer-name').value = data.customer.name || '';
        document.getElementById('customer-email').value = data.customer.email || '';
        document.getElementById('customer-address').value = data.customer.address || '';
      });
  });

  document.getElementById('checkout-btn').addEventListener('click', function () {
    errorEl.hidden = true;
    const totals = invoiceAmounts();
    const paidField = document.getElementById('paid-amount').value;
    const payload = {
      customer: {
        name: document.getElementById('customer-name').value,
        phone: document.getElementById('customer-phone').value,
        email: document.getElementById('customer-email').value,
        address: document.getElementById('customer-address').value,
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
      paid_amount: paidField === '' ? money(totals.total) : paidField,
      payment_method: document.getElementById('payment-method').value,
    };
    fetch(config.checkoutUrl, {
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
          errorEl.textContent = result.data.error || 'Could not complete the sale.';
          errorEl.hidden = false;
          return;
        }
        window.location.href = result.data.invoice_url;
      })
      .catch(function () {
        errorEl.textContent = 'Could not complete the sale.';
        errorEl.hidden = false;
      });
  });

  searchProducts('');
  renderCart();
})();
