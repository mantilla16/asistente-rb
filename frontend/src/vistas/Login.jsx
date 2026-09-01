import { useState } from "react";
import { api } from "../api";
import { Anillo, Boton } from "../comp/Piezas";

/**
 * Ingreso. Dos mitades: a la izquierda la identidad del producto sobre el
 * degradado de la marca, a la derecha el formulario sobre papel blanco.
 *
 * El panel de marca desaparece en móvil en vez de encogerse: una franja de
 * degradado de 80 píxeles no comunica nada y le quita sitio al formulario,
 * que es lo único que ahí importa.
 */
export default function Login({ onEntrar }) {
  const [usuario, setUsuario] = useState("");
  const [clave, setClave] = useState("");
  const [error, setError] = useState(null);
  const [ocupado, setOcupado] = useState(false);

  async function enviar(e) {
    e.preventDefault();
    setError(null);
    setOcupado(true);
    try {
      onEntrar(await api.login(usuario.trim(), clave));
    } catch (err) {
      setError(err.message);
      setClave("");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="marca-fondo relative hidden flex-col justify-between p-12 lg:flex">
        <div className="flex items-center gap-3">
          <Anillo tam={40} />
          <span className="text-lg font-semibold tracking-tight text-white">
            Russell Bedford
          </span>
        </div>

        <div>
          <h1 className="max-w-lg text-5xl font-bold leading-[1.05] tracking-tight text-white">
            Su conocimiento,<br />consultable.
          </h1>
          <p className="mt-6 max-w-md text-base leading-relaxed text-white/70">
            Cargue documentos, arme agentes con instrucciones propias y
            pregunte. Cada respuesta viene con la cita del fragmento del que
            salió, para que pueda verificarla.
          </p>
        </div>

        <p className="max-w-md text-xs leading-relaxed text-white/45">
          Los modelos corren en el servidor de la firma. Ningún documento
          sale hacia un proveedor externo.
        </p>
      </div>

      <div className="flex items-center justify-center px-6 py-12">
        <form onSubmit={enviar} className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <Anillo tam={34} />
            <span className="font-semibold tracking-tight">Russell Bedford</span>
          </div>

          <p className="rotulo">Asistente</p>
          <h2 className="mt-1 text-3xl font-bold tracking-tight texto-marca">
            Entrar
          </h2>
          <p className="mt-2 text-sm text-tinta-suave">
            Use sus credenciales del asistente. Son distintas de las de
            Analítica PUC.
          </p>

          <div className="mt-8 space-y-4">
            <label className="block">
              <span className="rotulo">Usuario</span>
              <input
                type="text" value={usuario} autoFocus autoComplete="username"
                onChange={(e) => setUsuario(e.target.value)}
                className="mt-1 w-full px-3 py-2.5 text-sm"
              />
            </label>
            <label className="block">
              <span className="rotulo">Contraseña</span>
              <input
                type="password" value={clave} autoComplete="current-password"
                onChange={(e) => setClave(e.target.value)}
                className="mt-1 w-full px-3 py-2.5 text-sm"
              />
            </label>
          </div>

          {error && (
            <p className="mt-4 rounded-[9px] bg-rojo-tenue px-3 py-2 text-sm text-rojo">
              {error}
            </p>
          )}

          <Boton tono="principal" type="submit"
                 disabled={ocupado || !usuario || !clave}
                 className="mt-6 w-full justify-center">
            {ocupado ? "Entrando…" : "Entrar"}
          </Boton>

          <p className="mt-8 text-xs leading-relaxed text-tinta-suave">
            ¿No tiene cuenta? Un administrador debe crearla. La primera se
            crea desde el servidor con{" "}
            <code className="cifra text-[11px]">python usuarios.py crear</code>.
          </p>
        </form>
      </div>
    </div>
  );
}
