document.addEventListener('DOMContentLoaded', function () {
  var $ = window.django && window.django.jQuery;
  if (!$) {
    console.error('Purchase item prefill: django.jQuery is missing');
    return;
  }

  function pricingUrl(id) {
    return '/admin/inventory/productunit/' + id + '/pricing/';
  }

  function parseNum(value) {
    var n = parseFloat(String(value || '').replace(/,/g, ''));
    return Number.isFinite(n) ? n : 0;
  }

  function money(value) {
    return value.toFixed(2);
  }

  function itemRow(el) {
    return $(el).closest('tr.form-row, .inline-related');
  }

  function productSelectSelector() {
    return '.inline-group .field-product_unit select';
  }

  function setReadonly($row, field, text) {
    var $cell = $row.find('.field-' + field);
    var $out = $cell.find('p, .readonly');
    if (!$out.length) {
      $out = $('<p class="readonly"></p>').appendTo($cell);
    }
    $out.text(text);
  }

  function updatePurchaseSubtotal() {
    var $subtotal = $('#id_subtotal');
    if (!$subtotal.length) {
      return;
    }
    var sum = 0;
    $('.inline-group tr.form-row').not('.empty-form').each(function () {
      var text = $(this).find('.field-total p, .field-total .readonly').first().text();
      sum += parseNum(text);
    });
    $subtotal.val(money(sum));
  }

  function updateLine($row) {
    if (!$row.length || $row.hasClass('empty-form')) {
      return;
    }

    var qty = parseNum($row.find('.field-quantity input').val());
    var price = parseNum($row.find('.field-unit_price input').val());
    var tax = parseNum($row.find('.field-tax input').val());
    var discountValue = parseNum($row.find('.field-discount_value input').val());
    var discountType = $row.find('.field-discount_type select').val();
    var conversion = parseNum($row.attr('data-conversion-to-base'));
    var subtotal = qty * price;
    var discount = discountType === 'percent' ? subtotal * discountValue / 100 : discountValue;
    if (discount > subtotal) {
      discount = subtotal;
    }

    setReadonly($row, 'total', money(Math.max(0, subtotal - discount + tax)));
    if (conversion) {
      setReadonly($row, 'base_quantity', (qty * conversion).toFixed(4));
    }
    updatePurchaseSubtotal();
  }

  function applyPricing($row, data, overwritePrice) {
    $row.attr('data-conversion-to-base', data.conversion_to_base);
    var $price = $row.find('.field-unit_price input');
    if (overwritePrice || !$price.val()) {
      $price.val(data.purchase_price).trigger('input');
    }
    var $qty = $row.find('.field-quantity input');
    if (!$qty.val()) {
      $qty.val('1');
    }
    updateLine($row);
  }

  function loadPricing($row, productUnitId, overwritePrice) {
    if (!productUnitId || !$row.length || $row.hasClass('empty-form')) {
      return;
    }
    fetch(pricingUrl(productUnitId), {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('HTTP ' + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        applyPricing($row, data, overwritePrice);
      })
      .catch(function (err) {
        console.error('Purchase item prefill: could not load pricing', err);
      });
  }

  $(document).on('select2:select', productSelectSelector(), function (event) {
    var id = event.params && event.params.data ? event.params.data.id : $(this).val();
    loadPricing(itemRow(this), id, true);
  });

  $(document).on('change', productSelectSelector(), function () {
    var $row = itemRow(this);
    var $price = $row.find('.field-unit_price input');
    loadPricing($row, $(this).val(), !$price.val());
  });

  $(document).on(
    'change input',
    '.inline-group .field-quantity input, .inline-group .field-unit_price input, .inline-group .field-tax input, .inline-group .field-discount_value input, .inline-group .field-discount_type select',
    function () {
      updateLine(itemRow(this));
    }
  );

  $(productSelectSelector()).each(function () {
    var $row = itemRow(this);
    var id = $(this).val();
    if (id) {
      loadPricing($row, id, false);
    } else {
      updateLine($row);
    }
  });
});
