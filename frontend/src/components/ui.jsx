// Minimal UI primitives used by the page components.
// Kept intentionally small: styling only, no application logic.

export function Container({ className = '', children, ...props }) {
  return (
    <div className={`mx-auto w-full max-w-5xl px-4 ${className}`} {...props}>
      {children}
    </div>
  )
}

export function Card({ className = '', children, ...props }) {
  return (
    <div
      className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ className = '', children, ...props }) {
  return (
    <div className={`border-b border-slate-100 px-6 py-4 ${className}`} {...props}>
      {children}
    </div>
  )
}

export function CardTitle({ className = '', children, ...props }) {
  return (
    <h2 className={`text-lg font-semibold text-slate-900 ${className}`} {...props}>
      {children}
    </h2>
  )
}

export function CardContent({ className = '', children, ...props }) {
  return (
    <div className={`px-6 py-4 text-slate-700 ${className}`} {...props}>
      {children}
    </div>
  )
}
