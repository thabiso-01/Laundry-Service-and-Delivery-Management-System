import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { Layout, RequireRole } from "./components/Layout";
import { AdminBusiness, AdminDriver, AdminIncidentDetail, AdminIncidents, RouteAlerts, Verification } from "./pages/admin/Admin";
import { ChangePassword, Landing, Login, Register } from "./pages/auth";
import { BusinessOrderDetail, BusinessOrders } from "./pages/business/BusinessOrders";
import { BusinessProfile, Services, Staff } from "./pages/business/BusinessSettings";
import { ScanBag } from "./pages/business/ScanBag";
import { LaundryPage } from "./pages/customer/LaundryPage";
import { OrderDetail, Orders } from "./pages/customer/Orders";
import { Search } from "./pages/customer/Search";
import { DriverHome, DriverJobPage } from "./pages/driver/Driver";
import { Documents, IncidentDetail, MyIncidents, NewIncident, Notifications, Security } from "./pages/shared";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            {/* Public */}
            <Route index element={<Landing />} />
            <Route path="login" element={<Login />} />
            <Route path="register" element={<Register />} />
            <Route path="search" element={<Search />} />
            <Route path="laundries/:id" element={<LaundryPage />} />

            {/* Any logged-in user */}
            <Route path="change-password" element={<RequireRole><ChangePassword /></RequireRole>} />
            <Route path="notifications" element={<RequireRole><Notifications /></RequireRole>} />
            <Route path="security" element={<RequireRole><Security /></RequireRole>} />
            <Route path="incidents" element={<RequireRole roles={["customer", "driver", "business"]}><MyIncidents /></RequireRole>} />
            <Route path="incidents/new" element={<RequireRole roles={["customer", "driver", "business"]}><NewIncident /></RequireRole>} />
            <Route path="incidents/:id" element={<RequireRole roles={["customer", "driver", "business"]}><IncidentDetail /></RequireRole>} />
            <Route path="documents" element={<RequireRole roles={["driver", "business"]}><Documents /></RequireRole>} />

            {/* Customer */}
            <Route path="orders" element={<RequireRole roles={["customer"]}><Orders /></RequireRole>} />
            <Route path="orders/:id" element={<RequireRole roles={["customer"]}><OrderDetail /></RequireRole>} />

            {/* Laundry business */}
            <Route path="business" element={<RequireRole roles={["business"]}><BusinessOrders /></RequireRole>} />
            <Route path="business/orders/:id" element={<RequireRole roles={["business"]}><BusinessOrderDetail /></RequireRole>} />
            <Route path="business/scan" element={<RequireRole roles={["business"]}><ScanBag /></RequireRole>} />
            <Route path="business/services" element={<RequireRole roles={["business"]}><Services /></RequireRole>} />
            <Route path="business/staff" element={<RequireRole roles={["business"]}><Staff /></RequireRole>} />
            <Route path="business/profile" element={<RequireRole roles={["business"]}><BusinessProfile /></RequireRole>} />

            {/* Driver */}
            <Route path="driver" element={<RequireRole roles={["driver"]}><DriverHome /></RequireRole>} />
            <Route path="driver/jobs/:id" element={<RequireRole roles={["driver"]}><DriverJobPage /></RequireRole>} />

            {/* Administrator */}
            <Route path="admin" element={<RequireRole roles={["admin"]}><Verification /></RequireRole>} />
            <Route path="admin/drivers/:id" element={<RequireRole roles={["admin"]}><AdminDriver /></RequireRole>} />
            <Route path="admin/businesses/:id" element={<RequireRole roles={["admin"]}><AdminBusiness /></RequireRole>} />
            <Route path="admin/incidents" element={<RequireRole roles={["admin"]}><AdminIncidents /></RequireRole>} />
            <Route path="admin/incidents/:id" element={<RequireRole roles={["admin"]}><AdminIncidentDetail /></RequireRole>} />
            <Route path="admin/routes" element={<RequireRole roles={["admin"]}><RouteAlerts /></RequireRole>} />

            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
