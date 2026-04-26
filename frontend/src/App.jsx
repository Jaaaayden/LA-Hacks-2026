import { Routes, Route, Navigate } from "react-router-dom";
import { KitProvider } from "./state/KitContext.jsx";
import Intake from "./screens/Intake.jsx";
import BuildKit from "./screens/BuildKit.jsx";
import Picker from "./screens/Picker.jsx";
import ActiveSearch from "./screens/ActiveSearch.jsx";

export default function App() {
  return (
    <KitProvider>
      <Routes>
        <Route path="/" element={<Intake />} />
        <Route path="/kit/:id" element={<BuildKit />} />
        <Route path="/pick/:id" element={<Picker />} />
        <Route path="/active/:id" element={<ActiveSearch />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </KitProvider>
  );
}
