import { getUser, isAuthenticated, logout } from '../state/session.js'

export function renderHeader(root) {
  const user = getUser()
  if (!isAuthenticated() || !user) {
    root.innerHTML = '<span class="brand">Acme Portal</span><a href="/login">Sign in</a>'
    return
  }
  root.innerHTML = `
    <span class="brand">Acme Portal</span>
    <span class="account">
      <img src="${user.avatarUrl ?? '/avatar-placeholder.svg'}" width="24" height="24" alt="" />
      <span>${user.name ?? user.email}</span>
      <button class="logout" type="button">Log out</button>
    </span>
  `
  root.querySelector('button.logout')?.addEventListener('click', () => {
    logout()
    renderHeader(root)
    window.location.assign('/login')
  })
}
