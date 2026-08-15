import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../lib/api";
import { AdminPage } from "./AdminPage";

const listClinicians = vi.fn();
const setClinicianRole = vi.fn();

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return {
    ...actual,
    api: {
      listClinicians: () => listClinicians(),
      setClinicianRole: (uid: string, role: string) => setClinicianRole(uid, role),
    },
  };
});

const CLINICIANS = [
  { uid: "u1", email: "admin@clinic.example", role: "admin", disabled: false },
  { uid: "u2", email: "b@clinic.example", role: "clinician", disabled: false },
];

describe("AdminPage", () => {
  beforeEach(() => {
    listClinicians.mockReset();
    setClinicianRole.mockReset();
  });

  it("lists every account and its role (A4)", async () => {
    listClinicians.mockResolvedValue(CLINICIANS);
    render(<AdminPage />);

    expect(await screen.findByText("admin@clinic.example")).toBeInTheDocument();
    expect(screen.getByText("b@clinic.example")).toBeInTheDocument();
  });

  it("changes a clinician's role and confirms it", async () => {
    listClinicians.mockResolvedValue(CLINICIANS);
    setClinicianRole.mockResolvedValue({ ...CLINICIANS[1], role: "admin" });
    render(<AdminPage />);
    await screen.findByText("b@clinic.example");

    fireEvent.change(screen.getByLabelText("Role for b@clinic.example"), {
      target: { value: "admin" },
    });

    await waitFor(() => expect(setClinicianRole).toHaveBeenCalledWith("u2", "admin"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      /b@clinic\.example is now admin/i,
    );
  });

  it("shows the backend's 403 for a non-admin caller, worded the same way", async () => {
    listClinicians.mockRejectedValue(
      new ApiError(403, "forbidden", "This action requires the 'admin' role.", []),
    );
    render(<AdminPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/requires the 'admin' role/i);
  });
});
