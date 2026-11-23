import './index.css'
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { Library } from './pages/Library'
import { Chat } from './pages/Chat'
import { AskPage } from './pages/AskPage'
import { SearchPage } from './pages/SearchPage'
import { Contradictions } from './pages/Contradictions'
import { Amendments } from './pages/Amendments'

function App() {
  return (
    <Router>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Library />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/ask" element={<AskPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/conflicts" element={<Contradictions />} />
          <Route path="/amendments" element={<Amendments />} />
        </Route>
      </Routes>
    </Router>
  )
}

export default App