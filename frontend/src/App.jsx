import './index.css'
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { Library } from './pages/Library'
import { Chat } from './pages/Chat'
import { AskPage } from './pages/AskPage'
import { SearchPage } from './pages/SearchPage'

function App() {
  return (
    <Router>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Library />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/ask" element={<AskPage />} />
          <Route path="/search" element={<SearchPage />} />
        </Route>
      </Routes>
    </Router>
  )
}

export default App