import { createContext, useContext, useState } from 'react'
import { login as apiLogin } from '../api/client'

const AuthContext = createContext(null)
const STORAGE_KEY = 'tabilo_auth'

function readStoredAuth() {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    // Corrupt/old data -- treat as logged out rather than crash the app.
    return null
  }
}

export function AuthProvider({ children }) {
  // Lazy initializer runs during the initial render (mount), so a page
  // refresh never flashes a "logged out" state before hydrating.
  const [auth, setAuth] = useState(readStoredAuth)

  async function login(username, password) {
    const data = await apiLogin(username, password) // throws on failure -- not swallowed here
    const authData = {
      token: data.token,
      user: { id: data.user_id, username: data.username, role: data.role },
      institution: data.institution,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(authData))
    setAuth(authData)
    return authData
  }

  function logout() {
    localStorage.removeItem(STORAGE_KEY)
    setAuth(null)
  }

  const value = {
    token: auth?.token ?? null,
    user: auth?.user ?? null,
    institution: auth?.institution ?? null,
    login,
    logout,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
