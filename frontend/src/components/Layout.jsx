import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

const MANAGEMENT_ROLES = ['ADMIN', 'COORDINATOR']

const navLinkClassName = ({ isActive }) =>
  `rounded px-3 py-1.5 text-sm font-medium ${
    isActive ? 'bg-purple-50 text-purple-700' : 'text-gray-600 hover:bg-gray-100'
  }`

export default function Layout({ children }) {
  const { user, institution, logout } = useAuth()
  const canManage = MANAGEMENT_ROLES.includes(user?.role)

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
        <div className="flex items-center gap-6">
          <p className="font-semibold text-gray-900">{institution?.name ?? 'Tabilo'}</p>
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={navLinkClassName}>
              Timetable
            </NavLink>
            {canManage && (
              <>
                <NavLink to="/teachers" className={navLinkClassName}>
                  Teachers
                </NavLink>
                <NavLink to="/subjects" className={navLinkClassName}>
                  Subjects
                </NavLink>
                <NavLink to="/course-requirements" className={navLinkClassName}>
                  Course Requirements
                </NavLink>
              </>
            )}
          </nav>
        </div>
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
