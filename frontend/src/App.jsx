import { useCallback, useEffect, useState } from "react";
import { api, cuandoExpireSesion } from "./api";
import { Anillo, Avatar, Aviso, Chip } from "./comp/Piezas";
import Login from "./vistas/Login";
import Chat from "./vistas/Chat";
import Documentos from "./vistas/Documentos";
import Agentes from "./vistas/Agentes";
import Usuarios from "./vistas/Usuarios";

export default function App() {
  const [yo, setYo] = useState(undefined);      // undefined = todavía no se sabe
  const [vista, setVista] = useState("chat");
  const [resaltar, setResaltar] = useState(null);
  const [agentes, setAgentes] = useState([]);
  const [ia, setIa] = useState(null);

  // Se pregunta al servidor si hay sesión en vez de recordarlo en el
  // navegador: la cookie es HttpOnly y el JavaScript no puede verla, que es
  // justo el punto.
  useEffect(() => {
    cuandoExpireSesion(() => setYo(null));
    api.yo().then(setYo).catch(() => setYo(null));
  }, []);

  const cargarAgentes = useCallback(() => {
    api.agentes().then(setAgentes).catch(() => setAgentes([]));
  }, []);

  useEffect(() => {
    if (!yo) return;
    cargarAgentes();
    api.estadoIA().then(setIa).catch(() => setIa(null));
  }, [yo, cargarAgentes]);

  if (yo === undefined) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Anillo tam={44} girando />
      </div>
    );
  }
  if (yo === null) return <Login onEntrar={setYo} />;

  const PESTANAS = [
    ["chat", "Conversar"],
    ["documentos", "Documentos"],
    ["agentes", "Agentes"],
    ...(yo.rol === "ADMIN" ? [["usuarios", "Usuarios"]] : []),
  ];

  function irA(destino, id) {
    setResaltar(id ?? null);
    setVista(destino);
  }

  const problema = ia && (!ia.arriba ? "apagado"
                   : ia.falta_chat ? "sin modelo de conversación"
                   : ia.falta_embed ? "sin modelo de embeddings" : null);

  return (
    <div className="min-h-screen">
      <div className="cinta-marca" />

      <header className="sticky top-0 z-30 border-b border-regla bg-papel-alto/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2">
          <div className="flex shrink-0 items-center gap-2">
            <Anillo tam={30} />
            <span className="hidden font-semibold tracking-tight sm:inline">
              Asistente <span className="texto-marca">RB</span>
            </span>
          </div>

          <nav className="flex flex-1 flex-wrap gap-1">
            {PESTANAS.map(([id, texto]) => (
              <button key={id} onClick={() => irA(id)}
                      className={`pestana ${vista === id ? "pestana-activa" : ""}`}>
                {texto}
              </button>
            ))}
          </nav>

          {problema && (
            <span title={ia?.error ?? "Revise Ollama en el servidor"}>
              <Chip tono="rojo">modelo {problema}</Chip>
            </span>
          )}

          <button onClick={() => api.logout().then(() => setYo(null))}
                  className="flex items-center gap-2" title="Salir">
            <Avatar nombre={yo.nombre} tam={30} />
            <span className="hidden text-sm sm:inline">{yo.nombre.split(" ")[0]}</span>
          </button>
        </div>
      </header>

      {problema && (
        <div className="mx-auto max-w-7xl px-4 pt-4">
          <Aviso tono="error" titulo={`El modelo está ${problema}`}>
            {!ia.arriba
              ? <>No hay respuesta de Ollama en <code className="cifra">{ia.url}</code>.
                  En el servidor: <code className="cifra">systemctl status ollama</code>.</>
              : <>Falta descargar el modelo. En el servidor:{" "}
                  <code className="cifra">
                    ollama pull {ia.falta_chat ? ia.modelo_chat : ia.modelo_embed}
                  </code>.</>}
          </Aviso>
        </div>
      )}

      {vista === "chat" && <Chat agentes={agentes} onIrA={irA} />}
      {vista === "documentos" && <Documentos resaltar={resaltar} />}
      {vista === "agentes" && <Agentes onCambio={cargarAgentes} />}
      {vista === "usuarios" && yo.rol === "ADMIN" && <Usuarios />}
    </div>
  );
}
