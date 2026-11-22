import './index.css'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { Library } from './pages/Library'
import { Chat } from './pages/Chat'

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Library />}>
          <Route index element={<Chat />} />
        </Route>
      </Routes>
    </Router>
  )
}

export default App