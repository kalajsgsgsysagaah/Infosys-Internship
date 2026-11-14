const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const start = source.indexOf('  function modal(');
const end = source.indexOf('\n  const closeModal=', start);
assert.notEqual(start, -1, 'modal renderer exists');
assert.notEqual(end, -1, 'modal renderer has a clear end');
const declaration = source.slice(start, end);

function createModalHarness() {
  const root = { innerHTML: '' };
  let closed = false;
  const backdropListeners = {};
  const backdrop = {
    addEventListener(name, listener) { backdropListeners[name] = listener; },
    click(target) { backdropListeners.click({ target }); },
  };
  const closeButtons = [
    { label: '×', listeners: {}, addEventListener(name, listener) { this.listeners[name] = listener; } },
    { label: 'Cancel', listeners: {}, addEventListener(name, listener) { this.listeners[name] = listener; } },
  ];
  const select = selector => {
    if (selector === '#modal-root') return root;
    if (selector === '.modal-backdrop') return backdrop;
    throw new Error('Unexpected selector: ' + selector);
  };
  const selectAll = selector => {
    assert.equal(selector, '[data-close-modal]');
    return closeButtons;
  };
  const render = new Function('$', '$$', 'esc', 'closeModal', `${declaration}\nreturn modal;`)(
    select,
    selectAll,
    value => String(value ?? ''),
    () => { closed = true; },
  );
  render('Test dialog', '', '<p>Body</p>', '<button>Cancel</button>');
  return {
    closeButtons,
    clickBackdrop: target => backdrop.click(target),
    isClosed: () => closed,
    backdrop,
  };
}

test('each dialog close button, including × and Cancel, dismisses the dialog', () => {
  const dialog = createModalHarness();
  for (const button of dialog.closeButtons) {
    button.listeners.click({ preventDefault() {} });
    assert.equal(dialog.isClosed(), true, `${button.label} dismisses the dialog`);
  }
});

test('backdrop click dismisses the dialog but a click inside does not', () => {
  const dialog = createModalHarness();
  dialog.clickBackdrop({});
  assert.equal(dialog.isClosed(), false);
  dialog.clickBackdrop(dialog.backdrop);
  assert.equal(dialog.isClosed(), true);
});
