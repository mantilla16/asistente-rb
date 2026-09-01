const BASE = import.meta.env.VITE_API ?? "/api";

/** La sesión puede vencer con la pestaña abierta. Sin este aviso, la
 *  pantalla se queda mostrando errores sueltos sin explicar por qué. */
let alExpirar = () => {};
export const cuandoExpireSesion = (fn) => { alExpirar = fn; };

async function pedir(ruta, opciones = {}) {
  const r = await fetch(BASE + ruta, { credentials: "same-origin", ...opciones });
  const texto = await r.text();
  let cuerpo = null;
  try { cuerpo = texto ? JSON.parse(texto) : null; } catch { cuerpo = texto; }
  if (!r.ok) {
    if (r.status === 401) alExpirar();
    const e = new Error(cuerpo?.detail ? String(cuerpo.detail) : r.statusText);
    e.estado = r.status;
    throw e;
  }
  return cuerpo;
}

const json = (metodo, cuerpo) => ({
  method: metodo,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cuerpo),
});

export const api = {
  login: (usuario, clave) => pedir("/auth/login", json("POST", { usuario, clave })),
  logout: () => pedir("/auth/logout", { method: "POST" }),
  yo: () => pedir("/auth/yo"),
  cambiarClave: (clave_actual, clave) =>
    pedir("/auth/clave", json("PUT", { clave_actual, clave })),

  estadoIA: () => pedir("/ia/estado"),

  documentos: () => pedir("/documentos"),
  subirDocumento: (form) => pedir("/documentos", { method: "POST", body: form }),
  editarDocumento: (id, d) => pedir(`/documentos/${id}`, json("PUT", d)),
  reprocesar: (id) => pedir(`/documentos/${id}/reprocesar`, { method: "POST" }),
  borrarDocumento: (id) => pedir(`/documentos/${id}`, { method: "DELETE" }),

  agentes: () => pedir("/agentes"),
  agente: (id) => pedir(`/agentes/${id}`),
  crearAgente: (a) => pedir("/agentes", json("POST", a)),
  editarAgente: (id, a) => pedir(`/agentes/${id}`, json("PUT", a)),
  borrarAgente: (id) => pedir(`/agentes/${id}`, { method: "DELETE" }),

  conversaciones: () => pedir("/conversaciones"),
  conversacion: (id) => pedir(`/conversaciones/${id}`),
  nuevaConversacion: (agente_id) =>
    pedir("/conversaciones", json("POST", { agente_id })),
  borrarConversacion: (id) => pedir(`/conversaciones/${id}`, { method: "DELETE" }),

  usuarios: () => pedir("/usuarios"),
  crearUsuario: (u) => pedir("/usuarios", json("POST", u)),
  editarUsuario: (id, u) => pedir(`/usuarios/${id}`, json("PUT", u)),
  reiniciarClave: (id, clave) => pedir(`/usuarios/${id}/clave`, json("PUT", { clave })),
};

/**
 * Envía la pregunta y entrega la respuesta a medida que llega.
 *
 * No usa EventSource porque esto es un POST con cuerpo y EventSource solo
 * hace GET. Se lee el flujo a mano, que además permite cancelar con un
 * AbortController cuando el usuario cambia de conversación.
 *
 * `onEvento` recibe cada evento del servidor: contexto (las citas), texto
 * (un trozo de respuesta), fin, ocupado o error.
 */
export async function preguntar(convId, texto, onEvento, señal) {
  const r = await fetch(`${BASE}/conversaciones/${convId}/mensajes`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ texto }),
    signal: señal,
  });
  if (!r.ok) {
    if (r.status === 401) alExpirar();
    throw new Error(`El servidor respondió ${r.status}`);
  }

  const lector = r.body.getReader();
  const dec = new TextDecoder();
  let resto = "";

  while (true) {
    const { done, value } = await lector.read();
    if (done) break;
    resto += dec.decode(value, { stream: true });
    // Un trozo de red puede cortar un evento por la mitad: se procesa
    // hasta el último separador completo y el resto espera al siguiente.
    const partes = resto.split("\n\n");
    resto = partes.pop();
    for (const p of partes) {
      const linea = p.replace(/^data: ?/, "").trim();
      if (!linea || linea === "[FIN]") continue;
      try { onEvento(JSON.parse(linea)); } catch { /* evento partido: se ignora */ }
    }
  }
}

export const fecha = (v) => {
  if (!v) return "—";
  const d = new Date(v);
  return d.toLocaleDateString("es-CO", { day: "2-digit", month: "2-digit", year: "numeric" });
};

export const hora = (v) => {
  if (!v) return "";
  return new Date(v).toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
};

export const pesoArchivo = (b) => {
  if (!b && b !== 0) return "—";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(0)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
};
