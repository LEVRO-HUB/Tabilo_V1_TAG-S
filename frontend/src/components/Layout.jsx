import { useAuth } from '../auth/AuthContext'

export default function Layout({ children }) {
  const { user, institution, logout } = useAuth()

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
        <p className="font-semibold text-gray-900">{institution?.name ?? 'Tabilo'}</p>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600">{user?.username}</span>
          <button
            type="button"
            onClick={logout}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
          >
            Log out
          </button>
        </div>
      </header>
      <main className="p-6">{children}</main>
    </div>
  )
}
