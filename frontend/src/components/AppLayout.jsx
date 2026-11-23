import { NavLink, Outlet } from 'react-router-dom'
import { Container } from '@/components/ui'
import { HealthBadge } from '@/components/HealthBadge'

const navLinkClass = ({ isActive }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition ${
    isActive
      ? 'bg-slate-900 text-white'
      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
  }`

export function AppLayout() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
        <Container className="flex flex-wrap items-center gap-4 py-3">
          <div className="mr-auto flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-slate-900 text-xs font-semibold text-white">
              VD
            </span>

            <div>
              <p className="text-sm font-semibold text-slate-900">
                VerifiDoc AI
              </p>
              <p className="text-xs text-slate-500">
                Evidence-grounded document intelligence
              </p>
            </div>
          </div>

          <nav
            className="flex w-full flex-wrap items-center gap-1 sm:w-auto"
            aria-label="Primary"
          >
            <NavLink to="/" end className={navLinkClass}>
              Documents
            </NavLink>

            <NavLink to="/ask" className={navLinkClass}>
              Ask
            </NavLink>

            <NavLink to="/search" className={navLinkClass}>
              Search
            </NavLink>
            <NavLink to="/conflicts" className={navLinkClass}>
              Compare
            </NavLink>
            <NavLink to="/amendments" className={navLinkClass}>
              Amendments
            </NavLink>
          </nav>

          <HealthBadge />
        </Container>
      </header>

      <main>
        <Outlet />
      </main>
    </div>
  )
}