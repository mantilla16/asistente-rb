/* Piezas compartidas. Nada de lógica de negocio: solo presentación. */

export function Boton({ tono = "contorno", className = "", ...props }) {
  return <button className={`btn btn-${tono} ${className}`} {...props} />;
}

export function Chip({ tono = "gris", children }) {
  return <span className={`chip chip-${tono}`}>{children}</span>;
}

export function Aviso({ tono = "info", titulo, children }) {
  const tonos = {
    ok: "border-verde bg-verde-tenue text-verde",
    error: "border-rojo bg-rojo-tenue text-rojo",
    alerta: "border-ambar bg-ambar-tenue text-ambar",
    info: "border-regla bg-papel-hondo text-tinta-media",
  };
  return (
    <div className={`rounded-[14px] border-l-[3px] px-4 py-3 text-sm ${tonos[tono]}`}>
      {titulo && <p className="font-semibold">{titulo}</p>}
      <div className={titulo ? "mt-0.5 text-tinta-media" : ""}>{children}</div>
    </div>
  );
}

/** El anillo del logo, dibujado. Es la firma visual del producto. */
export function Anillo({ tam = 34, girando = false }) {
  return (
    <svg width={tam} height={tam} viewBox="0 0 100 100"
         className={girando ? "girando" : ""} aria-hidden="true">
      <defs>
        <linearGradient id="anillo-rb" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#00bce4" />
          <stop offset="50%" stopColor="#ef8a00" />
          <stop offset="100%" stopColor="#92278f" />
        </linearGradient>
      </defs>
      <circle cx="50" cy="50" r="38" fill="none"
              stroke="url(#anillo-rb)" strokeWidth="13"
              strokeDasharray="180 60" strokeLinecap="round" />
    </svg>
  );
}

export function Avatar({ nombre, tam = 32 }) {
  const iniciales = (nombre || "?")
    .split(" ").filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
      style={{
        width: tam, height: tam, fontSize: tam * 0.4,
        background: "linear-gradient(120deg,#92278f,#0093b3)",
      }}
    >
      {iniciales}
    </span>
  );
}

export function Vacio({ titulo, children }) {
  return (
    <div className="panel panel-punteado px-6 py-10 text-center">
      <p className="text-sm font-semibold">{titulo}</p>
      <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-tinta-suave">
        {children}
      </p>
    </div>
  );
}

export function Modal({ titulo, onCerrar, children, ancho = "max-w-2xl" }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto
                    bg-tinta/30 p-4 backdrop-blur-sm"
         onClick={onCerrar}>
      <div className={`panel my-8 w-full ${ancho}`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-regla px-5 py-3">
          <p className="font-semibold">{titulo}</p>
          <button onClick={onCerrar} className="btn-texto text-lg leading-none">×</button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}

export function Campo({ etiqueta, ayuda, children }) {
  return (
    <label className="block">
      <span className="rotulo">{etiqueta}</span>
      <div className="mt-1">{children}</div>
      {ayuda && <p className="mt-1 text-xs leading-relaxed text-tinta-suave">{ayuda}</p>}
    </label>
  );
}
