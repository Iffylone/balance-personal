'use strict';
/* Balance personal - Sistema Contable Iffyware (version movil/PWA)
   Datos 100% locales (localStorage). Respaldo JSON compatible con la version de escritorio. */

// ---------- utilidades ----------
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const p2 = n => String(n).padStart(2, '0');
const dinero = v => '$' + Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const corto = v => { const a = Math.abs(v); if (a >= 1e6) return (v / 1e6).toFixed(1) + 'M'; if (a >= 1e3) return (v / 1e3).toFixed(1) + 'k'; return v.toFixed(0); };
const toIso = d => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const fromIso = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const hoyIso = () => toIso(new Date());
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const isoDisp = iso => { if (!iso) return ''; const [y, m, d] = iso.split('-'); return `${d}-${m}-${y}`; };
const nowIso = () => new Date().toISOString();
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
const MES_CORTO = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const fechaLarga = () => { const h = new Date(); return `${DIAS[h.getDay()]} ${h.getDate()} de ${MESES[h.getMonth()]} de ${h.getFullYear()}`; };
const num = v => { const n = parseFloat(String(v).replace(',', '.')); return isNaN(n) ? NaN : n; };
const norm = s => (s || '').split(/\s+/).filter(Boolean).join(' ');

const CAT_GAS = ['Alimentos y bebidas', 'Servicios', 'Transporte', 'Vivienda y hogar', 'Salud', 'Educación', 'Préstamos y deudas', 'Compras', 'Entretenimiento', 'Otros gastos'];
const CAT_ING = ['Salario cooperativa', 'Transferencias recibidas', 'Reintegros', 'Otros ingresos'];
const TIPO_DEUDA = ['Préstamo', 'Deuda', 'Servicio', 'Otro'];
const DEUDA_A_CAT = { 'Préstamo': 'Préstamos y deudas', 'Deuda': 'Préstamos y deudas', 'Servicio': 'Servicios', 'Otro': 'Otros gastos' };
const FORMAS = ['Efectivo', 'Transferencia', 'Tarjeta débito', 'Tarjeta crédito', 'Código QR', 'Otro'];
const COLORES = ['#E5484D', '#F59E0B', '#4F8CFF', '#7C5CFC', '#2FA36B', '#E91E63', '#0E9F8E', '#F97316', '#06B6D4', '#94A3B8', '#C084FC', '#84CC16'];

// ---------- almacenamiento ----------
const KEY = 'iffyware_contable_v1';
let D;
const vacio = () => ({ config: {}, movimientos: [], cuentas_por_pagar: [], cuentas: [], beneficiarios: [], seq: { m: 0, d: 0, c: 0, b: 0 } });
function cargar() {
  try { const s = localStorage.getItem(KEY); D = s ? JSON.parse(s) : vacio(); } catch (e) { D = vacio(); }
  D.seq = Object.assign({ m: 0, d: 0, c: 0, b: 0 }, D.seq || {});
  for (const k of ['movimientos', 'cuentas_por_pagar', 'cuentas', 'beneficiarios']) D[k] = D[k] || [];
  D.config = D.config || {};
}
function guardar() {
  try { localStorage.setItem(KEY, JSON.stringify(D)); }
  catch (e) { alert('No se pudo guardar los datos (almacenamiento lleno o bloqueado). Exportá un respaldo ya.'); }
}
const nid = k => ++D.seq[k];
const cfgGet = (k, def = null) => (k in D.config ? D.config[k] : def);
const cfgSet = (k, v) => { D.config[k] = String(v); guardar(); };
const isConfigured = () => cfgGet('admin_user') !== null;

// ---------- beneficiarios ----------
function upsertBenef(nombre, tipo, categoria, forma, cuenta, fecha, sumar = 1) {
  const limpio = norm(nombre), clave = limpio.toLowerCase();
  if (!clave) return;
  let b = D.beneficiarios.find(x => x.clave === clave);
  if (!b) { b = { id: nid('b'), clave, nombre: limpio, tipo: '', categoria: '', forma_pago: '', cuenta: '', veces: 0, ultimo_uso: '' }; D.beneficiarios.push(b); }
  b.veces += sumar;
  if ((fecha || '') >= (b.ultimo_uso || '')) Object.assign(b, { nombre: limpio, tipo, categoria: categoria || '', forma_pago: forma || '', cuenta: cuenta || '', ultimo_uso: fecha || '' });
}
const getBenefs = () => [...D.beneficiarios].sort((a, b) => b.veces - a.veces || a.nombre.localeCompare(b.nombre));
const getBenef = nombre => D.beneficiarios.find(b => b.clave === norm(nombre).toLowerCase());
function renameBenef(id, nuevo) {
  nuevo = norm(nuevo); const nk = nuevo.toLowerCase();
  const old = D.beneficiarios.find(b => b.id === id);
  if (!old || !nk) return;
  for (const m of D.movimientos) if (norm(m.origen_destino).toLowerCase() === old.clave) m.origen_destino = nuevo;
  const dest = D.beneficiarios.find(b => b.clave === nk && b.id !== id);
  if (dest) { dest.veces += old.veces; D.beneficiarios = D.beneficiarios.filter(b => b.id !== id); }
  else { old.clave = nk; old.nombre = nuevo; }
  guardar();
}
function delBenef(id) { D.beneficiarios = D.beneficiarios.filter(b => b.id !== id); guardar(); }

// ---------- movimientos ----------
function addMov(fecha, tipo, categoria, descripcion, origen, monto, forma, cuenta) {
  D.movimientos.push({ id: nid('m'), fecha, tipo, categoria, descripcion, origen_destino: origen, forma_pago: forma, cuenta, monto, creado_en: nowIso() });
  upsertBenef(origen, tipo, categoria, forma, cuenta, fecha, 1);
  guardar();
}
function updMov(id, fecha, categoria, descripcion, origen, monto, forma, cuenta) {
  const m = D.movimientos.find(x => x.id === id); if (!m) return;
  Object.assign(m, { fecha, categoria, descripcion, origen_destino: origen, monto, forma_pago: forma, cuenta });
  upsertBenef(origen, m.tipo, categoria, forma, cuenta, fecha, 0);
  guardar();
}
function delMov(id) { D.movimientos = D.movimientos.filter(m => m.id !== id); guardar(); }
const getMov = id => D.movimientos.find(m => m.id === id);
function getMovs(f = {}) {
  return D.movimientos.filter(m =>
    (!f.desde || m.fecha >= f.desde) && (!f.hasta || m.fecha <= f.hasta) &&
    (!f.tipo || m.tipo === f.tipo) && (!f.categoria || m.categoria === f.categoria))
    .sort((a, b) => (a.fecha < b.fecha ? 1 : a.fecha > b.fecha ? -1 : b.id - a.id));
}
const catsUsadas = tipo => [...new Set(D.movimientos.filter(m => m.tipo === tipo && m.categoria).map(m => m.categoria))].sort();

// ---------- cuentas ----------
const nombresCuentas = () => D.cuentas.map(c => c.nombre);
const signed = m => (m.tipo === 'ingreso' ? m.monto : -m.monto);
function saldoDe(nombre, ini) { let s = ini; for (const m of D.movimientos) if (m.cuenta === nombre) s += signed(m); return s; }
function saldosCuentas() {
  const nombres = nombresCuentas();
  const r = D.cuentas.map(c => ({ id: c.id, nombre: c.nombre, saldo_inicial: c.saldo_inicial, saldo_actual: saldoDe(c.nombre, c.saldo_inicial) }));
  let h = 0; for (const m of D.movimientos) if (!m.cuenta || !nombres.includes(m.cuenta)) h += signed(m);
  if (Math.abs(h) > 0.005) r.push({ id: null, nombre: 'Sin cuenta asignada', saldo_inicial: 0, saldo_actual: h });
  return r;
}
function addCuenta(nombre, saldo) {
  nombre = nombre.trim();
  if (D.cuentas.some(c => c.nombre === nombre)) throw new Error('Ya existe una cuenta con ese nombre.');
  D.cuentas.push({ id: nid('c'), nombre, saldo_inicial: saldo, creado_en: nowIso() }); guardar();
}
function editCuenta(id, nombre, saldo) {
  const c = D.cuentas.find(x => x.id === id); if (!c) return; nombre = nombre.trim();
  if (D.cuentas.some(x => x.nombre === nombre && x.id !== id)) throw new Error('Ya existe una cuenta con ese nombre.');
  if (c.nombre !== nombre) for (const m of D.movimientos) if (m.cuenta === c.nombre) m.cuenta = nombre;
  c.nombre = nombre; c.saldo_inicial = saldo; guardar();
}
function delCuenta(id) { D.cuentas = D.cuentas.filter(c => c.id !== id); guardar(); }
function cuentasHuerfanas() {
  const nombres = nombresCuentas(), g = {};
  for (const m of D.movimientos) if (!m.cuenta || !nombres.includes(m.cuenta)) {
    const k = m.cuenta || '(sin especificar)'; g[k] = g[k] || { valor: k, cantidad: 0, neto: 0 }; g[k].cantidad++; g[k].neto += signed(m);
  }
  return Object.values(g).sort((a, b) => b.cantidad - a.cantidad);
}
function reasignarCuenta(viejo, nuevo) {
  for (const m of D.movimientos) if (viejo === '(sin especificar)' ? !m.cuenta : m.cuenta === viejo) m.cuenta = nuevo;
  guardar();
}

// ---------- deudas ----------
function addDeuda(tipo, descripcion, acreedor, total, pagado, venc) {
  D.cuentas_por_pagar.push({ id: nid('d'), tipo, descripcion, acreedor, monto_total: total, monto_pagado: pagado, fecha_vencimiento: venc || null, estado: pagado >= total ? 'pagada' : 'pendiente', creado_en: nowIso() }); guardar();
}
function getDeudas(soloPend) {
  return D.cuentas_por_pagar.filter(d => !soloPend || d.estado === 'pendiente').sort((a, b) => {
    if ((a.estado === 'pendiente') !== (b.estado === 'pendiente')) return a.estado === 'pendiente' ? -1 : 1;
    if (!a.fecha_vencimiento !== !b.fecha_vencimiento) return a.fecha_vencimiento ? -1 : 1;
    if (a.fecha_vencimiento !== b.fecha_vencimiento) return a.fecha_vencimiento < b.fecha_vencimiento ? -1 : 1;
    return b.id - a.id;
  });
}
function abonar(id, monto) {
  const d = D.cuentas_por_pagar.find(x => x.id === id); if (!d) return;
  d.monto_pagado += monto; d.estado = d.monto_pagado >= d.monto_total ? 'pagada' : 'pendiente'; guardar();
}
function delDeuda(id) { D.cuentas_por_pagar = D.cuentas_por_pagar.filter(d => d.id !== id); guardar(); }
const totalPendiente = () => D.cuentas_por_pagar.filter(d => d.estado === 'pendiente').reduce((s, d) => s + d.monto_total - d.monto_pagado, 0);

// ---------- estadisticas ----------
function statsGastoDiario() {
  const por = {};
  for (const m of D.movimientos) if (m.tipo === 'gasto') por[m.fecha] = (por[m.fecha] || 0) + m.monto;
  const fechas = Object.keys(por);
  if (!fechas.length) return { total: 0, dias: 0, promedio: 0, prom7: 0, hoy: 0 };
  const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
  const primera = fromIso(fechas.sort()[0]);
  const dias = Math.max(Math.round((hoy - primera) / 864e5) + 1, 1);
  const total = Object.values(por).reduce((a, b) => a + b, 0);
  let suma7 = 0; for (let i = 0; i < 7; i++) suma7 += por[toIso(addDays(hoy, -i))] || 0;
  return { total, dias, promedio: total / dias, prom7: suma7 / Math.min(7, dias), hoy: por[toIso(hoy)] || 0 };
}
function gastoPorDia(n = 14) {
  const por = {}; for (const m of D.movimientos) if (m.tipo === 'gasto') por[m.fecha] = (por[m.fecha] || 0) + m.monto;
  const hoy = new Date(); hoy.setHours(0, 0, 0, 0); const out = [];
  for (let i = n - 1; i >= 0; i--) { const d = addDays(hoy, -i); out.push([d, por[toIso(d)] || 0]); }
  return out;
}
function categoriasResumen() {
  const g = {};
  for (const m of D.movimientos) { const k = m.tipo + '|' + m.categoria; g[k] = g[k] || { tipo: m.tipo, categoria: m.categoria, n: 0, total: 0 }; g[k].n++; g[k].total += m.monto; }
  return Object.values(g).sort((a, b) => (a.tipo < b.tipo ? 1 : a.tipo > b.tipo ? -1 : b.total - a.total));
}
function renameCategoria(tipo, viejo, nuevo) {
  nuevo = norm(nuevo); if (!nuevo || nuevo === viejo) return;
  for (const m of D.movimientos) if (m.tipo === tipo && m.categoria === viejo) m.categoria = nuevo;
  for (const b of D.beneficiarios) if (b.tipo === tipo && b.categoria === viejo) b.categoria = nuevo;
  guardar();
}
function promediosCategoria(desde, hasta, tipo = 'gasto') {
  const movs = D.movimientos.filter(m => m.tipo === tipo && (!desde || m.fecha >= desde) && (!hasta || m.fecha <= hasta));
  const hoy = new Date(); const h = hasta ? fromIso(hasta) : hoy;
  let d;
  if (desde) d = fromIso(desde);
  else { const f = D.movimientos.filter(m => m.tipo === 'gasto').map(m => m.fecha).sort()[0]; d = f ? fromIso(f) : hoy; }
  const meses = Math.max((h.getFullYear() - d.getFullYear()) * 12 + (h.getMonth() - d.getMonth()) + 1, 1);
  const g = {};
  for (const m of movs) { g[m.categoria] = g[m.categoria] || { categoria: m.categoria, n: 0, total: 0, maximo: 0 }; const x = g[m.categoria]; x.n++; x.total += m.monto; x.maximo = Math.max(x.maximo, m.monto); }
  const filas = Object.values(g).sort((a, b) => b.total - a.total);
  const tg = filas.reduce((s, f) => s + f.total, 0);
  for (const f of filas) { f.prom_mov = f.total / f.n; f.prom_mensual = f.total / meses; f.pct = tg ? f.total / tg * 100 : 0; }
  return { filas, meses, total: tg };
}
function resumenMensual(desde, hasta, max = 12) {
  const datos = {};
  for (const m of D.movimientos) {
    if ((desde && m.fecha < desde) || (hasta && m.fecha > hasta)) continue;
    const ym = m.fecha.slice(0, 7); datos[ym] = datos[ym] || { ingreso: 0, gasto: 0 }; datos[ym][m.tipo] += m.monto;
  }
  const claves = Object.keys(datos).sort(); if (!claves.length) return [];
  const fin = hasta ? fromIso(hasta) : new Date();
  let y = +claves[0].slice(0, 4), mo = +claves[0].slice(5, 7); const out = [];
  while (y < fin.getFullYear() || (y === fin.getFullYear() && mo <= fin.getMonth() + 1)) {
    const ym = `${y}-${p2(mo)}`, v = datos[ym] || { ingreso: 0, gasto: 0 }; out.push([ym, v.ingreso, v.gasto]);
    if (++mo === 13) { mo = 1; y++; }
  }
  return out.slice(-max);
}

// ---------- respaldo (formato compatible con la version de escritorio) ----------
const exportJson = () => JSON.stringify({ config: D.config, movimientos: D.movimientos, cuentas_por_pagar: D.cuentas_por_pagar, cuentas: D.cuentas, exportado_en: nowIso() }, null, 2);
function importJson(texto, modo) {
  const data = JSON.parse(texto);
  if (typeof data !== 'object' || !data || (!data.movimientos && !data.cuentas && !data.config)) throw new Error('El archivo no es un respaldo válido.');
  if (modo === 'reemplazar') { D.movimientos = []; D.cuentas_por_pagar = []; D.cuentas = []; D.beneficiarios = []; }
  for (const [k, v] of Object.entries(data.config || {})) D.config[k] = String(v);
  for (const c of data.cuentas || []) {
    const ex = D.cuentas.find(x => x.nombre === c.nombre);
    if (ex) ex.saldo_inicial = c.saldo_inicial || 0;
    else D.cuentas.push({ id: nid('c'), nombre: c.nombre, saldo_inicial: c.saldo_inicial || 0, creado_en: c.creado_en || nowIso() });
  }
  for (const m of data.movimientos || []) D.movimientos.push({ id: nid('m'), fecha: m.fecha, tipo: m.tipo, categoria: m.categoria, descripcion: m.descripcion || '', origen_destino: m.origen_destino || '', forma_pago: m.forma_pago || '', cuenta: m.cuenta || '', monto: m.monto, creado_en: m.creado_en || nowIso() });
  for (const m of data.movimientos || []) upsertBenef(m.origen_destino || '', m.tipo, m.categoria, m.forma_pago || '', m.cuenta || '', m.fecha, 1);
  for (const d of data.cuentas_por_pagar || []) D.cuentas_por_pagar.push({ id: nid('d'), tipo: d.tipo, descripcion: d.descripcion, acreedor: d.acreedor || '', monto_total: d.monto_total, monto_pagado: d.monto_pagado || 0, fecha_vencimiento: d.fecha_vencimiento || null, estado: d.estado || 'pendiente', creado_en: d.creado_en || nowIso() });
  guardar();
}
const csvCelda = v => { const s = String(v ?? ''); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
function csvDe(filas) {
  const cab = ['Fecha', 'Tipo', 'Categoría', 'Descripción', 'Origen/Destino', 'Forma de pago', 'Cuenta', 'Monto'];
  return '\ufeff' + [cab, ...filas.map(r => [r.fecha, r.tipo, r.categoria, r.descripcion, r.origen_destino, r.forma_pago, r.cuenta, r.monto])].map(f => f.map(csvCelda).join(',')).join('\r\n');
}
function descargar(nombre, texto, mime) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([texto], { type: mime })); a.download = nombre;
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
}

// ---------- autenticacion (mismo esquema que la version de escritorio) ----------
const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
const hexBytes = h => new Uint8Array(h.match(/../g).map(x => parseInt(x, 16)));
const cripto = () => { if (!(window.crypto && crypto.subtle)) throw new Error('Este navegador necesita abrir la app por HTTPS.'); return crypto.subtle; };
async function sha256hex(s) { return hex(await cripto().digest('SHA-256', new TextEncoder().encode(s))); }
const saltNuevo = () => hex(crypto.getRandomValues(new Uint8Array(16)));
async function crearAdmin(usuario, pass) {
  const salt = saltNuevo();
  D.config.admin_user = usuario; D.config.admin_salt = salt; D.config.admin_hash = await sha256hex(salt + pass); guardar();
}
async function verificarLogin(usuario, pass) {
  const u = cfgGet('admin_user'), h = cfgGet('admin_hash'), s = cfgGet('admin_salt');
  if (usuario !== u || !h) return false;
  return (await sha256hex(s + pass)) === h;
}
const normClave = c => (c || '').toUpperCase().split('').filter(ch => /[A-Z0-9]/.test(ch)).join('');
async function hashClave(claveNorm, saltHex) {
  const k = await cripto().importKey('raw', new TextEncoder().encode(claveNorm), 'PBKDF2', false, ['deriveBits']);
  return hex(await cripto().deriveBits({ name: 'PBKDF2', salt: hexBytes(saltHex), iterations: 120000, hash: 'SHA-256' }, k, 256));
}
const tieneClave = () => cfgGet('recovery_hash') !== null;
async function generarClave() {
  const cruda = hex(crypto.getRandomValues(new Uint8Array(8))).toUpperCase();
  const salt = saltNuevo();
  D.config.recovery_salt = salt; D.config.recovery_hash = await hashClave(cruda, salt); guardar();
  return cruda.match(/.{4}/g).join('-');
}
let intentos = 0, bloqueadoHasta = 0;
const segBloqueado = () => Math.max(0, Math.ceil((bloqueadoHasta - Date.now()) / 1000));
async function verificarClave(clave) {
  if (segBloqueado() > 0) return false;
  const h = cfgGet('recovery_hash'), s = cfgGet('recovery_salt'); if (!h || !s) return false;
  const ok = (await hashClave(normClave(clave), s)) === h;
  if (ok) intentos = 0; else if (++intentos >= 5) { bloqueadoHasta = Date.now() + 60000; intentos = 0; }
  return ok;
}
async function restablecerConClave(clave, nueva) {
  if (!(await verificarClave(clave))) return null;
  await crearAdmin(cfgGet('admin_user'), nueva);
  return await generarClave();
}

// =====================================================================
//                               INTERFAZ
// =====================================================================
let sesion = false, usuario = '', vista = 'inicio', filtroTxt = '', limite = 60;
let rep = { desde: '', hasta: '', tipo: '', cat: '' }, periodo = 'Todo el historial', soloPend = true;
const PERIODOS = ['Todo el historial', 'Este mes', 'Últimos 3 meses', 'Últimos 6 meses', 'Este año'];
const opt = (arr, sel) => arr.map(x => `<option${x === sel ? ' selected' : ''}>${esc(x)}</option>`).join('');

function sheet(titulo, html, mount) {
  const ov = $('#overlay');
  ov.innerHTML = `<div class="sheet-bg"></div><div class="sheet"><div class="sheet-h"><b>${esc(titulo)}</b><button class="x" aria-label="Cerrar">✕</button></div><div class="sheet-b">${html}</div></div>`;
  ov.classList.add('on');
  const close = () => { ov.classList.remove('on'); ov.innerHTML = ''; };
  $('.x', ov).onclick = close; $('.sheet-bg', ov).onclick = close;
  if (mount) mount($('.sheet-b', ov), close);
  return close;
}
const alerta = m => window.alert(m);

// ---------- pantallas de acceso ----------
function pantallaAcceso(html) { $('#app').innerHTML = `<div class="login"><img src="assets/icon_192.png" alt=""><h1>Balance personal</h1>${html}</div>`; }

function pantallaSetup() {
  pantallaAcceso(`<p>Configuración inicial</p>
    <label>Usuario administrador</label><input id="s_user" autocomplete="username">
    <div class="row2"><div><label>Contraseña</label><input id="s_p1" type="password" autocomplete="new-password"></div>
    <div><label>Repetir</label><input id="s_p2" type="password" autocomplete="new-password"></div></div>
    <label>Saldo inicial — Efectivo ($)</label><input id="s_ef" inputmode="decimal" value="0">
    <label>Saldo inicial — Banco Santander ($)</label><input id="s_sa" inputmode="decimal" value="0">
    <label>Saldo inicial — Personal Pay ($)</label><input id="s_pp" inputmode="decimal" value="0">
    <button class="btn verde" id="s_ok">Crear y entrar</button>
    <button class="link" id="s_imp">Ya tengo un respaldo de la PC: importarlo</button>
    <input type="file" id="s_file" accept=".json,application/json" hidden>`);
  $('#s_ok').onclick = async () => {
    const u = $('#s_user').value.trim(), p1 = $('#s_p1').value, p2v = $('#s_p2').value;
    const sal = ['#s_ef', '#s_sa', '#s_pp'].map(s => num($(s).value));
    if (!u) return alerta('Ingresá un usuario.');
    if (p1.length < 4) return alerta('La contraseña debe tener al menos 4 caracteres.');
    if (p1 !== p2v) return alerta('Las contraseñas no coinciden.');
    if (sal.some(isNaN)) return alerta('Los saldos iniciales deben ser números.');
    try {
      await crearAdmin(u, p1);
      ['Efectivo', 'Banco Santander', 'Personal Pay'].forEach((n, i) => { if (!D.cuentas.some(c => c.nombre === n)) addCuenta(n, sal[i]); });
      const clave = await generarClave();
      mostrarClave(clave, () => entrar(u), true);
    } catch (e) { alerta(e.message); }
  };
  $('#s_imp').onclick = () => $('#s_file').click();
  $('#s_file').onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try { importJson(await f.text(), 'reemplazar'); if (isConfigured()) { alerta('Respaldo importado. Ingresá con tu usuario y contraseña de la PC.'); pantallaLogin(); } else alerta('El respaldo se importó pero no tiene usuario. Creá uno.'); }
    catch (err) { alerta('No se pudo importar: ' + err.message); }
  };
}

function mostrarClave(clave, alCerrar, inicial) {
  pantallaAcceso(`<p>${inicial ? 'Configuración guardada.<br>' : ''}Tu clave de recuperación</p>
    <div class="clave" id="clave">${esc(clave)}</div>
    <p style="font-size:14px">Si olvidás la contraseña, esta clave es la única forma de entrar sin perder los datos. Anotala en papel o sacale una captura y guardala fuera de este teléfono. No se puede volver a mostrar.</p>
    <button class="btn gris" id="k_cp">Copiar</button><br><br>
    <button class="btn verde" id="k_ok">Ya la guardé, continuar</button>`);
  $('#k_cp').onclick = async () => { try { await navigator.clipboard.writeText(clave); $('#k_cp').textContent = 'Copiada ✓'; } catch (e) { alerta('No se pudo copiar. Anotala a mano.'); } };
  $('#k_ok').onclick = alCerrar;
}

function pantallaLogin() {
  pantallaAcceso(`<p>Acceso administrador</p>
    <label>Usuario</label><input id="l_user" autocomplete="username" autocapitalize="none">
    <label>Contraseña</label><input id="l_pass" type="password" autocomplete="current-password">
    <button class="btn" id="l_ok">Ingresar</button>
    <button class="link" id="l_olv">¿Olvidaste tu contraseña?</button>`);
  const intentar = async () => {
    try {
      if (await verificarLogin($('#l_user').value.trim(), $('#l_pass').value)) entrar($('#l_user').value.trim());
      else alerta('Usuario o contraseña incorrectos.');
    } catch (e) { alerta(e.message); }
  };
  $('#l_ok').onclick = intentar;
  $('#l_pass').onkeydown = e => { if (e.key === 'Enter') intentar(); };
  $('#l_olv').onclick = () => {
    if (!tieneClave()) return alerta('Esta instalación no tiene clave de recuperación. Sin la contraseña no hay forma de entrar sin perder los datos.');
    sheet('Restablecer contraseña', `<label>Clave de recuperación (XXXX-XXXX-XXXX-XXXX)</label><input id="r_clave" autocapitalize="characters" autocomplete="off">
      <label>Contraseña nueva</label><input id="r_p1" type="password"><label>Repetir contraseña nueva</label><input id="r_p2" type="password">
      <button class="btn verde" id="r_ok">Restablecer</button>`, (b, close) => {
      $('#r_ok', b).onclick = async () => {
        if (segBloqueado() > 0) return alerta(`Demasiados intentos. Esperá ${segBloqueado()} segundos.`);
        const p1 = $('#r_p1', b).value;
        if (p1.length < 4) return alerta('La contraseña debe tener al menos 4 caracteres.');
        if (p1 !== $('#r_p2', b).value) return alerta('Las contraseñas no coinciden.');
        try {
          const nueva = await restablecerConClave($('#r_clave', b).value, p1);
          if (!nueva) return alerta(segBloqueado() > 0 ? `Demasiados intentos. Esperá ${segBloqueado()} segundos.` : 'La clave de recuperación no es válida.');
          close(); mostrarClave(nueva, pantallaLogin, false);
        } catch (e) { alerta(e.message); }
      };
    });
  };
}

function entrar(u) { sesion = true; usuario = u; vista = 'inicio'; filtroTxt = ''; limite = 60; render(); }
function bloquear() { sesion = false; pantallaLogin(); }

// ---------- marco general ----------
const NAV = [['inicio', '🏠', 'Inicio'], ['reportes', '📄', 'Reportes'], ['analisis', '📊', 'Análisis'], ['deudas', '💳', 'Deudas'], ['mas', '☰', 'Más']];
function go(v) { vista = v; render(); window.scrollTo(0, 0); }
function marco(titulo, sub, cuerpo, conFab) {
  const activo = ['inicio', 'reportes', 'analisis', 'deudas'].includes(vista) ? vista : 'mas';
  $('#app').innerHTML = `<div class="top"><img src="assets/logo_small.png" alt=""><div><h1>${esc(titulo)}</h1>${sub ? `<small>${esc(sub)}</small>` : ''}</div><span class="sp"></span>
    ${vista === 'inicio' ? '' : '<button class="ib" id="b_home">‹ Inicio</button>'}</div>
    <main>${cuerpo}</main>
    ${conFab ? `<div class="fab"><button style="background:var(--rojo)" id="f_gasto">−  Gasto</button><button style="background:var(--verde)" id="f_ing">+  Ingreso</button></div>` : ''}
    <nav>${NAV.map(([k, i, t]) => `<button data-n="${k}" class="${k === activo ? 'on' : ''}"><span>${i}</span>${t}</button>`).join('')}</nav>`;
  $$('nav button').forEach(b => b.onclick = () => (b.dataset.n === 'mas' ? menuMas() : go(b.dataset.n)));
  if ($('#b_home')) $('#b_home').onclick = () => go('inicio');
  if (conFab) { $('#f_gasto').onclick = () => sheetMov('gasto'); $('#f_ing').onclick = () => sheetMov('ingreso'); }
}
function menuMas() {
  const items = [['cuentas', '🏦 Gestionar cuentas'], ['benef', '👥 Beneficiarios'], ['cats', '🏷️ Categorías'], ['datos', '💾 Respaldo y seguridad']];
  sheet('Más opciones', `<div class="menu">${items.map(([k, t]) => `<button data-v="${k}">${t}</button>`).join('')}<button data-v="_lock" style="color:#ff8f8f">🔒 Bloquear / salir</button></div>`, (b, close) => {
    $$('button', b).forEach(x => x.onclick = () => { close(); x.dataset.v === '_lock' ? bloquear() : go(x.dataset.v); });
  });
}
function render() {
  if (!sesion) return;
  ({ inicio: vInicio, reportes: vReportes, analisis: vAnalisis, deudas: vDeudas, cuentas: vCuentas, benef: vBenef, cats: vCats, datos: vDatos }[vista] || vInicio)();
}

// ---------- INICIO ----------
const ticket = m => `<div class="tk ${m.tipo}" data-id="${m.id}"><div class="m"><b>${esc(m.origen_destino || m.categoria)}</b><small>${esc(m.categoria)}${m.descripcion ? ' · ' + esc(m.descripcion) : ''}</small><small>${isoDisp(m.fecha)} · ${esc(m.cuenta || '-')} · ${esc(m.forma_pago || '-')}</small></div><div class="v">${m.tipo === 'gasto' ? '−' : '+'}${dinero(m.monto)}</div></div>`;
function vInicio() {
  const cu = saldosCuentas(), total = cu.reduce((s, c) => s + c.saldo_actual, 0), pend = totalPendiente(), neto = total - pend, st = statsGastoDiario();
  const card = (t, v, sub, col, vc) => `<div class="card"><i style="background:${col}"></i><div><small>${t}</small><b style="${vc ? 'color:' + vc : ''}">${v}</b><em>${esc(sub)}</em></div></div>`;
  marco('Balance personal', fechaLarga(), `
    <div class="cards">
      ${card('DISPONIBLE TOTAL', dinero(total), `${cu.length} cuenta(s)`, '#4F8CFF')}
      ${card('DEUDAS PENDIENTES', dinero(pend), pend > 0 ? 'Por pagar' : 'Sin deudas pendientes', '#F59E0B', pend > 0 ? '#F59E0B' : '')}
      ${card('NETO (DISP. − DEUDAS)', dinero(neto), 'Lo que realmente te queda', '#2FA36B', neto >= 0 ? '#6fd69b' : '#ff8f8f')}
      ${card('GASTO PROMEDIO / DÍA', dinero(st.promedio), `7 días: ${dinero(st.prom7)}\nHoy: ${dinero(st.hoy)}`, '#E5484D')}
    </div>
    <div class="chips">${cu.map(c => `<div class="chip">${esc(c.nombre)}<b class="${c.saldo_actual < 0 ? 'neg' : ''}">${dinero(c.saldo_actual)}</b></div>`).join('')}</div>
    <div class="bar"><h2 style="margin:0">Movimientos</h2><span id="cant"></span></div>
    <input id="busca" placeholder="Buscar (beneficiario, categoría, detalle…)" value="${esc(filtroTxt)}">
    <div id="lista"></div>`, true);
  $('#busca').oninput = e => { filtroTxt = e.target.value; limite = 60; pintarLista(); };
  pintarLista();
}
function pintarLista() {
  const t = filtroTxt.trim().toLowerCase();
  const todas = getMovs().filter(m => !t || [m.origen_destino, m.categoria, m.descripcion, m.cuenta, m.forma_pago, m.fecha, isoDisp(m.fecha)].join(' ').toLowerCase().includes(t));
  $('#cant').textContent = `${todas.length} registros`;
  const L = $('#lista');
  L.innerHTML = todas.length ? todas.slice(0, limite).map(ticket).join('') + (todas.length > limite ? `<button class="btn gris" id="mas">Ver más (${todas.length - limite})</button>` : '') : '<div class="vacio">No hay movimientos.</div>';
  $$('.tk', L).forEach(el => el.onclick = () => { const m = getMov(+el.dataset.id); if (m) sheetMov(m.tipo, m); });
  if ($('#mas')) $('#mas').onclick = () => { limite += 60; pintarLista(); };
}

function sheetMov(tipo, mov) {
  const edit = !!mov;
  if (!D.cuentas.length) return alerta("No hay ninguna cuenta. Creá una desde Más > Gestionar cuentas.");
  const cats = [...(tipo === 'ingreso' ? CAT_ING : CAT_GAS)]; catsUsadas(tipo).forEach(c => { if (!cats.includes(c)) cats.push(c); });
  if (edit && mov.categoria && !cats.includes(mov.categoria)) cats.push(mov.categoria);
  const cuentas = nombresCuentas(); if (edit && mov.cuenta && !cuentas.includes(mov.cuenta)) cuentas.push(mov.cuenta);
  const formas = [...FORMAS]; if (edit && mov.forma_pago && !formas.includes(mov.forma_pago)) formas.push(mov.forma_pago);
  const NUEVA = '➕  Nueva categoría…';
  const titulo = edit ? `Editar ${tipo}` : tipo === 'ingreso' ? 'Nuevo ingreso' : 'Nuevo gasto';
  sheet(titulo, `
    <label>Fecha</label><input type="date" id="f_fecha" value="${edit ? mov.fecha : hoyIso()}">
    <label>${tipo === 'ingreso' ? '¿De dónde proviene? (ej: cooperativa, jornada)' : '¿A quién se pagó / dónde se compró? (se recuerda)'}</label>
    <input id="f_origen" list="dl_b" autocomplete="off" value="${esc(edit ? mov.origen_destino : '')}"><datalist id="dl_b">${getBenefs().map(b => `<option value="${esc(b.nombre)}">`).join('')}</datalist>
    <label>Categoría</label><select id="f_cat">${opt(cats, edit ? mov.categoria : cats[0])}<option>${NUEVA}</option></select>
    <label>Descripción (detalle: qué se compró o pagó)</label><input id="f_desc" value="${esc(edit ? mov.descripcion : '')}">
    <label>Forma de pago</label><select id="f_forma">${opt(formas, edit ? mov.forma_pago : formas[0])}</select>
    <label>${tipo === 'ingreso' ? '¿A qué cuenta ingresa el dinero?' : '¿De qué cuenta se descuenta?'}</label><select id="f_cuenta">${opt(cuentas, edit ? mov.cuenta : cuentas[0])}</select>
    <label>Monto ($)</label><input id="f_monto" inputmode="decimal" placeholder="0.00" value="${edit ? mov.monto : ''}">
    <button class="btn ${tipo === 'ingreso' ? 'verde' : 'rojo'}" id="f_ok">${edit ? 'Guardar cambios' : 'Guardar'}</button>
    ${edit ? '<br><br><button class="btn gris" id="f_del">Eliminar este movimiento</button>' : ''}`, (b, close) => {
    let prev = $('#f_cat', b).value, ultimo = '';
    $('#f_cat', b).onchange = e => {
      if (e.target.value === NUEVA) {
        const n = norm(window.prompt('Nombre de la categoría:') || '');
        if (n) { if (![...e.target.options].some(o => o.value === n)) e.target.insertBefore(new Option(n, n), e.target.lastElementChild); e.target.value = n; } else e.target.value = prev;
      }
      prev = e.target.value;
    };
    const auto = () => {
      const clave = norm($('#f_origen', b).value).toLowerCase();
      if (edit || !clave || clave === ultimo) return;
      const be = getBenef(clave); if (!be) return; ultimo = clave;
      if (be.tipo === tipo && be.categoria) { const s = $('#f_cat', b); if (![...s.options].some(o => o.value === be.categoria)) s.insertBefore(new Option(be.categoria, be.categoria), s.lastElementChild); s.value = be.categoria; prev = be.categoria; }
      if (formas.includes(be.forma_pago)) $('#f_forma', b).value = be.forma_pago;
      if (cuentas.includes(be.cuenta)) $('#f_cuenta', b).value = be.cuenta;
    };
    $('#f_origen', b).onchange = auto; $('#f_origen', b).onblur = auto;
    $('#f_ok', b).onclick = () => {
      const monto = num($('#f_monto', b).value);
      if (!(monto > 0)) return alerta('Ingresá un monto válido mayor a cero.');
      const fecha = $('#f_fecha', b).value; if (!fecha) return alerta('Elegí una fecha.');
      const cat = $('#f_cat', b).value; if (!cat || cat === NUEVA) return alerta('La categoría no puede quedar vacía.');
      const cuenta = $('#f_cuenta', b).value; if (!cuenta) return alerta('Elegí la cuenta.');
      const args = [fecha, cat, $('#f_desc', b).value.trim(), norm($('#f_origen', b).value), monto, $('#f_forma', b).value, cuenta];
      if (edit) updMov(mov.id, ...args); else addMov(fecha, tipo, cat, args[2], args[3], monto, args[5], cuenta);
      close(); render();
    };
    if (edit) $('#f_del', b).onclick = () => { if (confirm('¿Eliminar este movimiento?')) { delMov(mov.id); close(); render(); } };
  });
}

// ---------- DEUDAS ----------
function vDeudas() {
  const L = getDeudas(soloPend);
  marco('Cuentas por pagar', `Pendiente total: ${dinero(totalPendiente())}`, `
    <div class="row2"><button class="btn amb" id="d_new">+ Nueva deuda</button><button class="btn gris" id="d_tog">${soloPend ? 'Ver todas' : 'Solo pendientes'}</button></div>
    <h2>${soloPend ? 'Pendientes' : 'Todas'}</h2>
    ${L.length ? L.map(d => {
      const pend = d.monto_total - d.monto_pagado, pct = Math.min(100, d.monto_total ? d.monto_pagado / d.monto_total * 100 : 100);
      return `<div class="lst"><div class="t"><b>${esc(d.descripcion)}</b><b>${dinero(Math.max(pend, 0))}</b></div>
        <small>${esc(d.tipo)}${d.acreedor ? ' · ' + esc(d.acreedor) : ''}${d.fecha_vencimiento ? ' · vence ' + isoDisp(d.fecha_vencimiento) : ''}</small>
        <div class="prog"><i style="width:${pct}%"></i></div><small>Pagado ${dinero(d.monto_pagado)} de ${dinero(d.monto_total)} · ${d.estado}</small>
        <div class="acts">${d.estado === 'pendiente' ? `<button class="btn sm verde" data-ab="${d.id}">Abonar / pagar</button>` : ''}<button class="btn sm gris" data-del="${d.id}">Eliminar</button></div></div>`;
    }).join('') : '<div class="vacio">No hay deudas.</div>'}`);
  $('#d_new').onclick = sheetDeuda;
  $('#d_tog').onclick = () => { soloPend = !soloPend; render(); };
  $$('[data-ab]').forEach(b => b.onclick = () => sheetAbonar(+b.dataset.ab));
  $$('[data-del]').forEach(b => b.onclick = () => { if (confirm('¿Eliminar esta deuda? Los gastos ya registrados no se borran.')) { delDeuda(+b.dataset.del); render(); } });
}
function sheetDeuda() {
  sheet('Nueva deuda', `
    <label>Tipo</label><select id="n_tipo">${opt(TIPO_DEUDA)}</select>
    <label>Descripción</label><input id="n_desc">
    <label>Acreedor (a quién se le debe)</label><input id="n_acr" list="dl_a" autocomplete="off"><datalist id="dl_a">${getBenefs().map(b => `<option value="${esc(b.nombre)}">`).join('')}</datalist>
    <div class="row2"><div><label>Monto total ($)</label><input id="n_tot" inputmode="decimal"></div><div><label>Ya pagado ($)</label><input id="n_pag" inputmode="decimal" value="0"></div></div>
    <label>Fecha de vencimiento (opcional)</label><input type="date" id="n_ven">
    <button class="btn amb" id="n_ok">Guardar</button>`, (b, close) => {
    $('#n_ok', b).onclick = () => {
      const desc = $('#n_desc', b).value.trim(), tot = num($('#n_tot', b).value), pag = num($('#n_pag', b).value || '0');
      if (!desc) return alerta('Ingresá una descripción.');
      if (!(tot > 0)) return alerta('Ingresá un monto total válido.');
      if (isNaN(pag) || pag < 0) return alerta('El monto pagado no es válido.');
      addDeuda($('#n_tipo', b).value, desc, norm($('#n_acr', b).value), tot, pag, $('#n_ven', b).value); close(); render();
    };
  });
}
function sheetAbonar(id) {
  const d = D.cuentas_por_pagar.find(x => x.id === id); if (!d) return;
  if (!D.cuentas.length) return alerta('No hay ninguna cuenta de donde descontar.');
  const pend = d.monto_total - d.monto_pagado;
  sheet('Abonar / pagar', `<b>${esc(d.descripcion)}</b><p style="color:var(--mut);margin:2px 0 12px">Pendiente actual: ${dinero(pend)}</p>
    <label>Monto a abonar ($)</label><input id="a_monto" inputmode="decimal">
    <label>Forma de pago</label><select id="a_forma">${opt(FORMAS)}</select>
    <label>Cuenta de donde sale el dinero</label><select id="a_cuenta">${opt(nombresCuentas())}</select>
    <button class="btn verde" id="a_ok">Registrar abono</button>`, (b, close) => {
    $('#a_ok', b).onclick = () => {
      const m = num($('#a_monto', b).value); if (!(m > 0)) return alerta('Ingresá un monto válido.');
      if (m > pend + 0.01 && !confirm(`El monto (${dinero(m)}) es mayor al pendiente (${dinero(pend)}). ¿Continuar igual?`)) return;
      addMov(hoyIso(), 'gasto', DEUDA_A_CAT[d.tipo] || 'Otros gastos', `Abono a: ${d.descripcion}`, d.acreedor || '', m, $('#a_forma', b).value, $('#a_cuenta', b).value);
      abonar(id, m); close(); render();
    };
  });
}

// ---------- REPORTES ----------
function vReportes() {
  const todas = [...new Set([...CAT_ING, ...CAT_GAS, ...D.movimientos.map(m => m.categoria)])].sort();
  marco('Reportes', '', `
    <div class="row2"><div><label>Desde</label><input type="date" id="r_d" value="${rep.desde}"></div><div><label>Hasta</label><input type="date" id="r_h" value="${rep.hasta}"></div></div>
    <div class="row2"><div><label>Tipo</label><select id="r_t"><option value="">Todos</option><option value="ingreso"${rep.tipo === 'ingreso' ? ' selected' : ''}>Ingreso</option><option value="gasto"${rep.tipo === 'gasto' ? ' selected' : ''}>Gasto</option></select></div>
    <div><label>Categoría</label><select id="r_c"><option value="">Todas</option>${opt(todas, rep.cat)}</select></div></div>
    <div id="r_res"></div>`);
  const pintar = () => {
    rep = { desde: $('#r_d').value, hasta: $('#r_h').value, tipo: $('#r_t').value, cat: $('#r_c').value };
    const f = getMovs({ desde: rep.desde, hasta: rep.hasta, tipo: rep.tipo, categoria: rep.cat });
    const ing = f.filter(m => m.tipo === 'ingreso').reduce((s, m) => s + m.monto, 0), gas = f.filter(m => m.tipo === 'gasto').reduce((s, m) => s + m.monto, 0);
    $('#r_res').innerHTML = `<div class="cards"><div class="card"><i style="background:var(--verde)"></i><div><small>INGRESOS</small><b class="pos">${dinero(ing)}</b></div></div>
      <div class="card"><i style="background:var(--rojo)"></i><div><small>GASTOS</small><b class="neg">${dinero(gas)}</b></div></div></div>
      <div class="bar"><span>${f.length} movimiento(s) · Neto <b class="${ing - gas >= 0 ? 'pos' : 'neg'}">${dinero(ing - gas)}</b></span><button class="btn sm gris" id="r_csv">Exportar CSV</button></div>
      ${f.slice(0, 300).map(ticket).join('') || '<div class="vacio">Sin resultados.</div>'}${f.length > 300 ? '<div class="vacio">Se muestran 300; exportá el CSV para ver todos.</div>' : ''}`;
    $$('#r_res .tk').forEach(el => el.onclick = () => { const m = getMov(+el.dataset.id); if (m) sheetMov(m.tipo, m); });
    $('#r_csv').onclick = () => descargar(`reporte_${hoyIso()}.csv`, csvDe(f), 'text/csv;charset=utf-8');
  };
  ['#r_d', '#r_h', '#r_t', '#r_c'].forEach(s => $(s).onchange = pintar);
  pintar();
}

// ---------- ANÁLISIS ----------
function inicioMesAtras(n) { const h = new Date(); let y = h.getFullYear(), m = h.getMonth() + 1 - n; while (m <= 0) { m += 12; y--; } return new Date(y, m - 1, 1); }
function rangoPeriodo(n) {
  const h = new Date();
  if (n === 'Este mes') return [toIso(new Date(h.getFullYear(), h.getMonth(), 1)), toIso(h)];
  if (n === 'Últimos 3 meses') return [toIso(inicioMesAtras(2)), toIso(h)];
  if (n === 'Últimos 6 meses') return [toIso(inicioMesAtras(5)), toIso(h)];
  if (n === 'Este año') return [`${h.getFullYear()}-01-01`, toIso(h)];
  return [null, null];
}
function pieSvg(data) {
  const vis = data.filter(d => d.v > 0), tot = vis.reduce((s, d) => s + d.v, 0);
  if (tot <= 0) return '<div class="vacio">Sin datos en este período.</div>';
  const R = 80, C = 100; let a0 = -Math.PI / 2, paths = '';
  if (vis.length === 1) paths = `<circle cx="${C}" cy="${C}" r="${R}" fill="${vis[0].c}"/>`;
  else for (const d of vis) {
    const a1 = a0 + d.v / tot * 2 * Math.PI;
    paths += `<path d="M${C},${C} L${C + R * Math.cos(a0)},${C + R * Math.sin(a0)} A${R},${R} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${C + R * Math.cos(a1)},${C + R * Math.sin(a1)} Z" fill="${d.c}" stroke="#12141c" stroke-width="1.5"/>`; a0 = a1;
  }
  return `<svg viewBox="0 0 200 200" style="width:200px;max-width:60%;display:block;margin:6px auto">${paths}</svg>
    <div class="leg">${vis.map(d => `<span><i style="background:${d.c}"></i>${esc(d.l)} ${dinero(d.v)} (${(d.v / tot * 100).toFixed(1)}%)</span>`).join('')}</div>`;
}
function barrasSvg(filas, dos) { // filas: [etiqueta, v1, v2]
  if (!filas.length) return '<div class="vacio">Sin datos.</div>';
  const max = Math.max(...filas.map(f => Math.max(f[1], dos ? f[2] : 0)), 1), W = Math.max(filas.length * (dos ? 46 : 30) + 20, 300), H = 170, base = H - 28, alto = base - 18;
  let s = '';
  filas.forEach((f, i) => {
    const x = 10 + i * (dos ? 46 : 30);
    if (dos) {
      const h1 = f[1] / max * alto, h2 = f[2] / max * alto;
      s += `<rect x="${x}" y="${base - h1}" width="16" height="${h1}" fill="#2FA36B" rx="2"/><rect x="${x + 18}" y="${base - h2}" width="16" height="${h2}" fill="#E5484D" rx="2"/>`;
      if (f[2] > 0) s += `<text x="${x + 26}" y="${base - h2 - 3}" font-size="8" fill="#8b92a8" text-anchor="middle">${corto(f[2])}</text>`;
    } else {
      const h1 = f[1] / max * alto; s += `<rect x="${x}" y="${base - h1}" width="22" height="${h1}" fill="#E5484D" rx="2"/>`;
      if (f[1] > 0) s += `<text x="${x + 11}" y="${base - h1 - 3}" font-size="8" fill="#8b92a8" text-anchor="middle">${corto(f[1])}</text>`;
    }
    s += `<text x="${x + (dos ? 17 : 11)}" y="${H - 12}" font-size="9" fill="#8b92a8" text-anchor="middle">${esc(f[0])}</text>`;
  });
  return `<div class="sc"><svg viewBox="0 0 ${W} ${H}" style="width:${W}px;height:${H}px">${s}</svg></div>`;
}
function vAnalisis() {
  marco('Análisis y gráficos', '', `<label>Período</label><select id="p_sel">${opt(PERIODOS, periodo)}</select><div id="p_res"></div>`);
  const pintar = () => {
    periodo = $('#p_sel').value; const [d, h] = rangoPeriodo(periodo);
    const fil = getMovs({ desde: d, hasta: h });
    const ing = fil.filter(m => m.tipo === 'ingreso').reduce((s, m) => s + m.monto, 0), gas = fil.filter(m => m.tipo === 'gasto').reduce((s, m) => s + m.monto, 0), pend = totalPendiente();
    const pc = promediosCategoria(d, h, 'gasto'), pi = promediosCategoria(d, h, 'ingreso');
    const mensual = resumenMensual(d, h, 12).map(([ym, i, g]) => [MES_CORTO[+ym.slice(5, 7) - 1] + ' ' + ym.slice(2, 4), i, g]);
    const diario = gastoPorDia(14).map(([dt, v]) => [String(dt.getDate()), v]);
    const tabla = pc.filas.length ? `<div class="sc"><table><tr><th>Categoría</th><th>N°</th><th>Total</th><th>Prom/mov</th><th>Prom/mes</th><th>%</th></tr>${pc.filas.map(f => `<tr><td>${esc(f.categoria)}</td><td>${f.n}</td><td>${dinero(f.total)}</td><td>${dinero(f.prom_mov)}</td><td>${dinero(f.prom_mensual)}</td><td>${f.pct.toFixed(1)}%</td></tr>`).join('')}</table></div><small style="color:var(--mut)">Meses considerados: ${pc.meses}</small>` : '';
    $('#p_res').innerHTML = `
      <div class="cards"><div class="card"><i style="background:var(--verde)"></i><div><small>INGRESOS</small><b class="pos">${dinero(ing)}</b></div></div>
      <div class="card"><i style="background:var(--rojo)"></i><div><small>GASTOS</small><b class="neg">${dinero(gas)}</b></div></div>
      <div class="card"><i style="background:var(--amb)"></i><div><small>DEUDAS PENDIENTES</small><b style="color:var(--amb)">${dinero(pend)}</b></div></div></div>
      <h2>Ingresos vs gastos vs deudas</h2>${pieSvg([{ l: 'Ingresos', v: ing, c: '#2FA36B' }, { l: 'Gastos', v: gas, c: '#E5484D' }, { l: 'Deudas pendientes', v: pend, c: '#F59E0B' }])}
      <h2>Gastos por categoría</h2>${pieSvg(pc.filas.map((f, i) => ({ l: f.categoria, v: f.total, c: COLORES[i % COLORES.length] })))}${tabla}
      <h2>Ingresos por categoría</h2>${pieSvg(pi.filas.map((f, i) => ({ l: f.categoria, v: f.total, c: COLORES[i % COLORES.length] })))}
      <h2>Evolución mensual <small style="color:var(--mut)">(verde ingresos · rojo gastos)</small></h2>${barrasSvg(mensual, true)}
      <h2>Gasto de los últimos 14 días</h2>${barrasSvg(diario, false)}`;
  };
  $('#p_sel').onchange = pintar; pintar();
}

// ---------- CUENTAS ----------
function vCuentas() {
  const cu = saldosCuentas(), hu = cuentasHuerfanas(), nombres = nombresCuentas();
  marco('Gestionar cuentas', '', `<button class="btn" id="c_new">+ Nueva cuenta</button><h2>Cuentas</h2>
    ${cu.map(c => `<div class="lst"><div class="t"><b>${esc(c.nombre)}</b><b class="${c.saldo_actual < 0 ? 'neg' : ''}">${dinero(c.saldo_actual)}</b></div>
      ${c.id ? `<small>Saldo inicial ${dinero(c.saldo_inicial)}</small><div class="acts"><button class="btn sm gris" data-ed="${c.id}">Editar</button><button class="btn sm gris" data-del="${c.id}">Eliminar</button></div>` : '<small>Movimientos sin cuenta válida: reasignalos abajo.</small>'}</div>`).join('') || '<div class="vacio">No hay cuentas.</div>'}
    ${hu.length && nombres.length ? `<h2>Movimientos con cuenta inexistente</h2>${hu.map((h, i) => `<div class="lst"><b>${esc(h.valor)}</b><br><small>${h.cantidad} movimiento(s) · neto ${dinero(h.neto)}</small>
      <select data-hs="${i}">${opt(nombres)}</select><button class="btn sm amb" data-hr="${i}">Reasignar a esa cuenta</button></div>`).join('')}` : ''}`);
  $('#c_new').onclick = () => sheetCuenta();
  $$('[data-ed]').forEach(b => b.onclick = () => sheetCuenta(D.cuentas.find(c => c.id === +b.dataset.ed)));
  $$('[data-del]').forEach(b => b.onclick = () => {
    const c = D.cuentas.find(x => x.id === +b.dataset.del); if (!c) return;
    const n = D.movimientos.filter(m => m.cuenta === c.nombre).length;
    if (confirm(n ? `La cuenta "${c.nombre}" tiene ${n} movimiento(s). Si la eliminás quedarán sin cuenta válida. ¿Eliminar?` : `¿Eliminar la cuenta "${c.nombre}"?`)) { delCuenta(c.id); render(); }
  });
  $$('[data-hr]').forEach(b => b.onclick = () => { const i = +b.dataset.hr; reasignarCuenta(hu[i].valor, $(`[data-hs="${i}"]`).value); render(); });
}
function sheetCuenta(c) {
  sheet(c ? 'Editar cuenta' : 'Nueva cuenta', `<label>Nombre</label><input id="u_n" value="${esc(c ? c.nombre : '')}"><label>Saldo inicial ($)</label><input id="u_s" inputmode="decimal" value="${c ? c.saldo_inicial : 0}"><button class="btn verde" id="u_ok">Guardar</button>`, (b, close) => {
    $('#u_ok', b).onclick = () => {
      const n = $('#u_n', b).value.trim(), s = num($('#u_s', b).value); if (!n) return alerta('Ingresá un nombre.'); if (isNaN(s)) return alerta('El saldo no es válido.');
      try { c ? editCuenta(c.id, n, s) : addCuenta(n, s); close(); render(); } catch (e) { alerta(e.message); }
    };
  });
}

// ---------- BENEFICIARIOS / CATEGORÍAS ----------
function vBenef() {
  const L = getBenefs();
  marco('Beneficiarios', `${L.length} guardados`, `<p style="color:var(--mut);font-size:14px">Se guardan solos al registrar movimientos. Renombrar uno con el nombre de otro los unifica.</p>
    ${L.map(b => `<div class="lst"><div class="t"><b>${esc(b.nombre)}</b><small>${b.veces} vez/veces</small></div><small>${esc(b.categoria || '-')} · ${esc(b.forma_pago || '-')} · ${esc(b.cuenta || '-')}</small>
      <div class="acts"><button class="btn sm gris" data-rn="${b.id}">Renombrar</button><button class="btn sm gris" data-del="${b.id}">Eliminar</button></div></div>`).join('') || '<div class="vacio">Todavía no hay beneficiarios.</div>'}`);
  $$('[data-rn]').forEach(x => x.onclick = () => { const b = D.beneficiarios.find(y => y.id === +x.dataset.rn); const n = window.prompt('Nuevo nombre:', b.nombre); if (n && norm(n)) { renameBenef(b.id, n); render(); } });
  $$('[data-del]').forEach(x => x.onclick = () => { if (confirm('¿Quitar de la lista? Los movimientos no se borran.')) { delBenef(+x.dataset.del); render(); } });
}
function vCats() {
  const L = categoriasResumen();
  marco('Categorías', '', `${['gasto', 'ingreso'].map(t => `<h2>${t === 'gasto' ? 'Gastos' : 'Ingresos'}</h2>${L.filter(x => x.tipo === t).map(c => `<div class="lst"><div class="t"><b>${esc(c.categoria)}</b><b>${dinero(c.total)}</b></div><small>${c.n} movimiento(s)</small>
      <div class="acts"><button class="btn sm gris" data-t="${t}" data-c="${esc(c.categoria)}">Renombrar</button></div></div>`).join('') || '<div class="vacio">Sin categorías.</div>'}`).join('')}`);
  $$('[data-c]').forEach(x => x.onclick = () => { const n = window.prompt('Nuevo nombre de la categoría:', x.dataset.c); if (n && norm(n)) { renameCategoria(x.dataset.t, x.dataset.c, n); render(); } });
}

// ---------- RESPALDO Y SEGURIDAD ----------
function vDatos() {
  marco('Respaldo y seguridad', '', `
    <h2>Respaldo</h2><p style="color:var(--mut);font-size:14px">El archivo es compatible con la versión de PC (Importar / Exportar). Hacé un respaldo seguido: si borrás los datos del navegador, se pierde todo.</p>
    <button class="btn verde" id="x_exp">Exportar respaldo (.json)</button><br><br>
    <button class="btn" id="x_imp">Importar respaldo…</button><input type="file" id="x_file" accept=".json,application/json" hidden>
    <h2>Seguridad</h2><button class="btn gris" id="x_pass">Cambiar contraseña</button><br><br>
    <button class="btn gris" id="x_key">Generar nueva clave de recuperación</button><br><br>
    <button class="btn rojo" id="x_lock">Bloquear / salir</button>
    <p style="color:var(--mut);font-size:12px;margin-top:20px">${D.movimientos.length} movimientos · ${D.cuentas.length} cuentas · ${D.cuentas_por_pagar.length} deudas · usuario: ${esc(usuario)}</p>`);
  $('#x_exp').onclick = () => descargar(`respaldo_contable_${hoyIso().replace(/-/g, '')}.json`, exportJson(), 'application/json');
  $('#x_imp').onclick = () => $('#x_file').click();
  $('#x_file').onchange = async e => {
    const f = e.target.files[0]; if (!f) return; let txt;
    try { txt = await f.text(); JSON.parse(txt); } catch (err) { return alerta('El archivo no es un JSON válido.'); }
    sheet('Importar respaldo', `<p>Archivo: <b>${esc(f.name)}</b></p><label>Modo</label><select id="i_modo"><option value="fusionar">Fusionar (agrega a lo que ya hay)</option><option value="reemplazar">Reemplazar (borra movimientos, cuentas y deudas actuales)</option></select>
      <button class="btn verde" id="i_ok">Importar</button>`, (b, close) => {
      $('#i_ok', b).onclick = () => {
        const modo = $('#i_modo', b).value;
        if (modo === 'reemplazar' && !confirm('Se borrarán los datos actuales de este teléfono. ¿Continuar?')) return;
        try { importJson(txt, modo); close(); alerta('Respaldo importado.'); render(); } catch (err) { alerta('No se pudo importar: ' + err.message); }
      };
    });
  };
  $('#x_pass').onclick = () => sheet('Cambiar contraseña', `<label>Contraseña actual</label><input id="p_a" type="password"><label>Contraseña nueva</label><input id="p_n" type="password"><label>Repetir nueva</label><input id="p_r" type="password"><button class="btn verde" id="p_ok">Cambiar</button>`, (b, close) => {
    $('#p_ok', b).onclick = async () => {
      try {
        if (!(await verificarLogin(usuario, $('#p_a', b).value))) return alerta('La contraseña actual es incorrecta.');
        const n = $('#p_n', b).value; if (n.length < 4) return alerta('Mínimo 4 caracteres.'); if (n !== $('#p_r', b).value) return alerta('No coinciden.');
        await crearAdmin(usuario, n); close(); alerta('Contraseña cambiada.');
      } catch (e) { alerta(e.message); }
    };
  });
  $('#x_key').onclick = async () => {
    if (!confirm('Se invalida la clave anterior y se genera una nueva. ¿Continuar?')) return;
    try { const k = await generarClave(); mostrarClave(k, () => { render(); }, false); } catch (e) { alerta(e.message); }
  };
  $('#x_lock').onclick = bloquear;
}

// ---------- arranque ----------
function arrancar() {
  cargar();
  try { if (navigator.storage && navigator.storage.persist) navigator.storage.persist(); } catch (e) { /* opcional */ }
  if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('sw.js').catch(() => {});
  isConfigured() ? pantallaLogin() : pantallaSetup();
}
if (typeof window !== 'undefined' && !window.__TEST__) arrancar();
